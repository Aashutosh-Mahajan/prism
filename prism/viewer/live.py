"""Live paired runs: one task through a coding agent in two disposable copies.

Without PRISM gets a plain source copy. With PRISM gets the same copy plus the real PRISM index and the
agent's PRISM integration. Both runs happen at once; their messages, terminal commands and token
counters are streamed to the dashboard, and an optional check command is run in each finished copy to see
whether the result is still correct.

Agents: Claude Code, Codex and Antigravity (`agy -p`) all run headless. Antigravity cannot ask for
permission in print mode, so it reads, searches and edits files but its shell commands are denied.
Folder copies are not an OS sandbox; the agent is limited to its own folder only by the agent's own rules.
"""

from __future__ import annotations

import difflib
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prism.core.errors import NotFoundError, UserError
from prism.writers.json_writer import write_json

ARMS = ("without", "with")
MAX_EVENTS = 3000
MAX_TEXT = 1500
MAX_OUTPUT = 2500
SNAPSHOT_FILE_LIMIT = 512 * 1024
SNAPSHOT_TOTAL_LIMIT = 64 * 1024 * 1024
ACTIVE = ("preparing", "running", "checking", "awaiting_manual")
# Files PRISM's own integration adds or an agent run produces. They are not part of the solution.
_NOISE_DIRS = {
    ".git",
    ".aicontext",
    ".claude",
    ".codex",
    ".agent",
    ".agents",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
_NOISE_FILES = {".mcp.json"}
CLAUDE_TOOLS = (
    "Read Glob Grep Edit Write Bash(python:*) Bash(pytest:*) Bash(prism:*) Bash(npm test:*)"
)
_MODEL = re.compile(r"^[A-Za-z0-9._:\[\]/-]{1,80}$")
_SHELL_TOOLS = ("Bash", "PowerShell")


# --- helpers ------------------------------------------------------------------------------


# Print mode denies every shell command, and a model that tries one first often stops. Both arms get
# the same note, so it changes nothing about the comparison except that the run does the work.
_AGY_NOTE = (
    "\n\nNote: shell commands are not available in this environment. Use your file listing, "
    "search, read and edit tools, and make the requested edits yourself."
)


def _only_prism_hooks(path: Path) -> bool:
    try:
        hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
        commands = [
            str(h.get("command", ""))
            for groups in hooks.values()
            for group in groups
            for h in group.get("hooks", [])
        ]
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    return bool(commands) and all(c.startswith("prism hook ") for c in commands)


_PACKAGE_ROOT = Path(__file__).resolve().parents[2].as_posix()


def _prism_shim(directory: Path) -> Path:
    """A `prism` command that runs this interpreter and this checkout, found from any shell.

    The interpreter's own folder is not where pip puts `prism.exe` (that is `Scripts`), and an
    agent's Bash tool needs an extensionless script, so the With copy gets small shims instead."""
    directory.mkdir(parents=True, exist_ok=True)
    python = Path(sys.executable).as_posix()
    root = Path(__file__).resolve().parents[2].as_posix()
    posix = (
        "#!/bin/sh" + chr(10)
        + f'PYTHONPATH="{root}${{PYTHONPATH:+:$PYTHONPATH}}" exec "{python}" -m prism "$@"' + chr(10)
    )
    windows = chr(13).join(
        ["@echo off", f'set "PYTHONPATH={root};%PYTHONPATH%"', f'"{python}" -m prism %*', ""]
    ).replace(chr(13), chr(13) + chr(10))
    (directory / "prism").write_bytes(posix.encode())
    (directory / "prism").chmod(0o755)
    (directory / "prism.cmd").write_bytes(windows.encode())
    return directory


def _kill(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        process.kill()


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    value = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    if len(value) <= limit:
        return value
    return value[:limit] + f" … ({len(value) - limit} more characters)"


def _snapshot(directory: Path) -> dict[str, bytes] | None:
    files: dict[str, bytes] = {}
    total = 0
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if (
            not path.is_file()
            or any(part in _NOISE_DIRS for part in relative.parts)
            or path.name in _NOISE_FILES
        ):
            continue
        size = path.stat().st_size
        total += size
        if total > SNAPSHOT_TOTAL_LIMIT:
            return None
        files[relative.as_posix()] = path.read_bytes() if size <= SNAPSHOT_FILE_LIMIT else b""
    return files


def _changes(before: dict[str, bytes] | None, directory: Path) -> tuple[str, list[str], int, int]:
    """Unified diff of text files, the changed paths, and lines added and removed."""
    after = _snapshot(directory) if before is not None else None
    if before is None or after is None:
        return "Source tree too large to diff.", [], 0, 0
    changed: list[str] = []
    chunks: list[str] = []
    added = removed = 0
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        changed.append(path)
        try:
            a = old.decode("utf-8").splitlines(keepends=True) if old is not None else []
            b = new.decode("utf-8").splitlines(keepends=True) if new is not None else []
        except UnicodeDecodeError:
            chunks.append(f"Binary file changed: {path}\n")
            continue
        lines = list(
            difflib.unified_diff(
                a,
                b,
                fromfile="/dev/null" if old is None else f"a/{path}",
                tofile="/dev/null" if new is None else f"b/{path}",
            )
        )
        added += sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
        removed += sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
        chunks.append("".join(lines))
    return _clip("".join(chunks), 60000), changed, added, removed


def usage_totals(raw: dict[str, Any] | None) -> dict[str, int] | None:
    """Normalised counters. Cache reads and writes are input the model processed."""
    if not isinstance(raw, dict):
        return None
    fresh = int(raw.get("input_tokens") or 0)
    created = int(raw.get("cache_creation_input_tokens") or 0)
    read = int(raw.get("cache_read_input_tokens") or 0)
    output = int(raw.get("output_tokens") or 0)
    return {
        "input_tokens": fresh,
        "cache_creation_tokens": created,
        "cache_read_tokens": read,
        "output_tokens": output,
        "input_total": fresh + created + read,
        "total_tokens": fresh + created + read + output,
    }


def _empty_arm() -> dict[str, Any]:
    return {
        "state": "waiting",
        "events": [],
        "usage": None,
        "usage_final": False,
        "turns": None,
        "started": None,
        "finished": None,
        "duration_seconds": None,
        "cost_usd": None,
        "commands_run": 0,
        "final_text": "",
        "error": None,
        "patch": "",
        "files_changed": [],
        "lines_added": 0,
        "lines_removed": 0,
        "check": None,
    }


def compare(arms: dict[str, dict[str, Any]], check_given: bool) -> dict[str, Any]:
    """Savings and whether the solution stayed as good. Never invents a missing number."""
    without, with_ = arms["without"], arms["with"]

    def pct(read: Any) -> float | None:
        a, b = read(without), read(with_)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not a:
            return None
        return float((a - b) / a * 100)

    def usage(key: str) -> Any:
        return lambda arm: (arm["usage"] or {}).get(key)

    finished = all(arm["state"] == "completed" for arm in arms.values())
    if not finished:
        quality = "incomplete"
    elif not check_given:
        quality = "unverified"
    else:
        a = bool((without["check"] or {}).get("passed"))
        b = bool((with_["check"] or {}).get("passed"))
        quality = "same" if a and b else "degraded" if a else "better" if b else "both_failed"

    def when(value: float | None) -> float | None:
        return value if finished else None

    return {
        "quality": quality,
        "token_saving_pct": when(pct(usage("total_tokens"))),
        "input_saving_pct": when(pct(usage("input_total"))),
        "output_saving_pct": when(pct(usage("output_tokens"))),
        "cost_saving_pct": when(pct(lambda arm: arm["cost_usd"])),
        "time_saving_pct": when(pct(lambda arm: arm["duration_seconds"])),
        "commands_saving_pct": when(pct(lambda arm: arm["commands_run"])),
        "identical_patch": bool(finished and without["patch"] == with_["patch"]),
    }


# --- agent adapters -----------------------------------------------------------------------


@dataclass
class Update:
    """What one line of an agent's output means."""

    events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None
    final: bool = False
    cost: float | None = None
    turns: int | None = None
    text: str | None = None
    failed: str | None = None
    done: bool = False


class ClaudeStream:
    """`claude -p --output-format stream-json`."""

    def __init__(self) -> None:
        self._seen: dict[str, dict[str, Any]] = {}
        self._shell: set[str] = set()

    def feed(self, message: dict[str, Any]) -> Update:
        update = Update()
        kind = message.get("type")
        if kind == "system" and message.get("subtype") == "init":
            update.events.append(
                {"kind": "info", "text": f"Started · model {message.get('model', 'unknown')}"}
            )
        elif kind == "assistant" and isinstance(message.get("message"), dict):
            body = message["message"]
            ident = body.get("id")
            if isinstance(ident, str) and isinstance(body.get("usage"), dict):
                self._seen[ident] = body["usage"]  # the last report for a message id is its total
                update.usage = usage_totals(
                    {
                        key: sum(int(u.get(key) or 0) for u in self._seen.values())
                        for key in (
                            "input_tokens",
                            "cache_creation_input_tokens",
                            "cache_read_input_tokens",
                            "output_tokens",
                        )
                    }
                )
            for block in body.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    update.events.append({"kind": "text", "text": _clip(block["text"])})
                elif block.get("type") == "tool_use":
                    name = str(block.get("name", "tool"))
                    raw_input = block.get("input")
                    data: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
                    if name in _SHELL_TOOLS and isinstance(data.get("command"), str):
                        self._shell.add(str(block.get("id")))
                        update.events.append(
                            {
                                "kind": "terminal_start",
                                "id": str(block.get("id")),
                                "command": _clip(data["command"], 600),
                            }
                        )
                    else:
                        summary = ""
                        for key in (
                            "file_path",
                            "path",
                            "pattern",
                            "url",
                            "description",
                            "command",
                        ):
                            if isinstance(data.get(key), str) and data[key]:
                                summary = _clip(data[key], 300)
                                break
                        update.events.append({"kind": "tool", "name": name, "text": summary})
        elif kind == "user" and isinstance(message.get("message"), dict):
            for block in message["message"].get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        str(part.get("text", "")) for part in content if isinstance(part, dict)
                    )
                ok = not block.get("is_error")
                ident = str(block.get("tool_use_id"))
                if ident in self._shell:
                    update.events.append(
                        {
                            "kind": "terminal_end",
                            "id": ident,
                            "output": _clip(content or "", MAX_OUTPUT),
                            "ok": ok,
                        }
                    )
                else:
                    update.events.append(
                        {"kind": "result", "ok": ok, "text": _clip(content or "", 600)}
                    )
        elif kind == "result":
            update.usage = usage_totals(message.get("usage"))
            update.final = update.usage is not None
            cost = message.get("total_cost_usd")
            update.cost = float(cost) if isinstance(cost, (int, float)) else None
            turns = message.get("num_turns")
            update.turns = turns if isinstance(turns, int) else None
            update.text = _clip(message.get("result") or "", 4000)
            update.done = True
            if message.get("is_error"):
                update.failed = _clip(message.get("result") or "The agent reported an error", 500)
        return update


class CodexStream:
    """`codex exec --json`: one JSON event per line."""

    def __init__(self) -> None:
        self._started: set[str] = set()
        self._input = self._cached = self._output = 0
        self._turns = 0

    def feed(self, message: dict[str, Any]) -> Update:
        update = Update()
        kind = message.get("type")
        raw_item = message.get("item")
        item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
        if kind == "thread.started":
            update.events.append({"kind": "info", "text": "Started Codex session"})
        elif kind in ("item.started", "item.completed"):
            item_type, ident = item.get("type"), str(item.get("id"))
            if item_type == "command_execution":
                if ident not in self._started:
                    self._started.add(ident)
                    update.events.append(
                        {
                            "kind": "terminal_start",
                            "id": ident,
                            "command": _clip(item.get("command") or "", 600),
                        }
                    )
                if kind == "item.completed":
                    code = item.get("exit_code")
                    update.events.append(
                        {
                            "kind": "terminal_end",
                            "id": ident,
                            "output": _clip(item.get("aggregated_output") or "", MAX_OUTPUT),
                            "ok": code in (0, None) and item.get("status") != "failed",
                        }
                    )
            elif kind == "item.completed":
                if item_type == "agent_message" and item.get("text"):
                    update.events.append({"kind": "text", "text": _clip(item["text"])})
                elif item_type == "reasoning" and item.get("text"):
                    update.events.append(
                        {"kind": "info", "text": "Thinking: " + _clip(item["text"], 240)}
                    )
                elif item_type == "file_change":
                    paths = ", ".join(
                        str(c.get("path")) for c in item.get("changes") or [] if isinstance(c, dict)
                    )
                    update.events.append(
                        {"kind": "tool", "name": "Edit", "text": _clip(paths, 300)}
                    )
                elif item_type in ("mcp_tool_call", "web_search"):
                    update.events.append(
                        {
                            "kind": "tool",
                            "name": str(item.get("tool") or item_type),
                            "text": _clip(item.get("query") or item.get("arguments") or "", 300),
                        }
                    )
                elif item_type == "error":
                    update.events.append(
                        {
                            "kind": "result",
                            "ok": False,
                            "text": _clip(item.get("message") or "", 600),
                        }
                    )
        elif kind == "turn.completed" and isinstance(message.get("usage"), dict):
            usage = message["usage"]
            self._input += int(usage.get("input_tokens") or 0)
            self._cached += int(usage.get("cached_input_tokens") or 0)
            self._output += int(usage.get("output_tokens") or 0)
            self._turns += 1
            update.usage = usage_totals(
                {
                    "input_tokens": max(0, self._input - self._cached),
                    "cache_read_input_tokens": self._cached,
                    "output_tokens": self._output,
                }
            )
            update.final = True
            update.turns = self._turns
            update.done = True
        elif kind in ("turn.failed", "error"):
            error = message.get("error")
            text = error.get("message") if isinstance(error, dict) else message.get("message")
            update.failed = _clip(text or "Codex reported an error", 500)
            update.events.append({"kind": "result", "ok": False, "text": update.failed})
        return update


class AntigravityStream:
    """`agy -p --output-format stream-json`: step updates, then one result with total usage."""

    def __init__(self) -> None:
        self._text: dict[int, str] = {}
        self._usage: dict[int, dict[str, Any]] = {}
        self._shell: set[int] = set()

    def _totals(self) -> dict[str, int] | None:
        if not self._usage:
            return None
        return usage_totals(
            {
                "input_tokens": sum(int(u.get("input_tokens") or 0) for u in self._usage.values()),
                "cache_read_input_tokens": sum(
                    int(u.get("cache_read_tokens") or 0) for u in self._usage.values()
                ),
                "output_tokens": sum(int(u.get("output_tokens") or 0) for u in self._usage.values()),
            }
        )

    def feed(self, message: dict[str, Any]) -> Update:
        update = Update()
        kind = message.get("event")
        if kind == "init":
            init = message.get("init") if isinstance(message.get("init"), dict) else {}
            mode = init.get("permission_mode") or "default"
            update.events.append({"kind": "info", "text": f"Started Antigravity session · {mode}"})
        elif kind == "step_update" and isinstance(message.get("step_update"), dict):
            step = message["step_update"]
            index = int(step.get("step_index") or 0)
            state, step_type = step.get("state"), step.get("step_type")
            if step_type == "agent_response":
                if isinstance(step.get("text_delta"), str):
                    self._text[index] = self._text.get(index, "") + step["text_delta"]
                if state == "DONE":
                    if isinstance(step.get("usage"), dict):
                        self._usage[index] = step["usage"]
                        update.usage = self._totals()
                    text = self._text.pop(index, "").strip()
                    if text:
                        update.events.append({"kind": "text", "text": _clip(text)})
            elif step_type == "tool":
                name = str(step.get("tool_name") or "tool")
                raw = step.get("tool_info")
                info: dict[str, Any] = raw if isinstance(raw, dict) else {}
                raw_params = info.get("parameters")
                params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
                error = info.get("error")
                if name == "run_command":
                    command = _clip(str(params.get("CommandLine") or params.get("command") or ""), 600)
                    if state == "ACTIVE":
                        self._shell.add(index)
                        update.events.append(
                            {"kind": "terminal_start", "id": str(index), "command": command}
                        )
                    elif state in ("DONE", "ERROR"):
                        if index not in self._shell:
                            update.events.append(
                                {"kind": "terminal_start", "id": str(index), "command": command}
                            )
                        output = error.get("message") if isinstance(error, dict) else info.get("output")
                        update.events.append(
                            {
                                "kind": "terminal_end",
                                "id": str(index),
                                "output": _clip(output or "", MAX_OUTPUT),
                                "ok": state == "DONE",
                            }
                        )
                elif state == "ACTIVE":
                    summary = ""
                    for key in ("Path", "AbsolutePath", "TargetFile", "Query", "Pattern", "Url"):
                        if isinstance(params.get(key), str) and params[key]:
                            summary = _clip(params[key], 300)
                            break
                    update.events.append({"kind": "tool", "name": name, "text": summary})
                elif state == "ERROR":
                    text = error.get("message") if isinstance(error, dict) else name
                    update.events.append({"kind": "result", "ok": False, "text": _clip(text, 600)})
        elif kind == "result" and isinstance(message.get("result"), dict):
            result = message["result"]
            raw_usage = result.get("usage")
            if isinstance(raw_usage, dict):
                self._usage = {0: raw_usage}
                update.usage = self._totals()
                update.final = True
            turns = result.get("num_turns")
            update.turns = turns if isinstance(turns, int) else None
            update.text = _clip(result.get("response") or "", 4000)
            update.done = True
            denied = result.get("denied_actions")
            if isinstance(denied, list) and denied:
                names = ", ".join(sorted({str(d.get("action")) for d in denied if isinstance(d, dict)}))
                update.events.append(
                    {
                        "kind": "info",
                        "text": f"Antigravity's headless mode cannot ask permission, so it denied: {names}. "
                        "File reads, searches and edits still work.",
                    }
                )
            if result.get("status") != "SUCCESS":
                update.failed = _clip(result.get("error") or "Antigravity reported an error", 500)
        return update


@dataclass
class Agent:
    id: str
    name: str
    manual: bool = False
    init_agent: str = ""
    stdin_prompt: bool = True  # False: the task is part of the command line

    def find(self) -> list[str] | None:
        return None

    def version(self, base: list[str]) -> tuple[str | None, bool | None]:
        """The agent's version text and whether it is logged in (None when it cannot tell)."""
        return None, None

    def command(
        self, base: list[str], model: str, turns: int, directory: Path, task: str = ""
    ) -> list[str]:
        raise NotImplementedError

    def stream(self) -> ClaudeStream | CodexStream | AntigravityStream:
        raise NotImplementedError


def _run_text(command: list[str], timeout: float = 20) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


class ClaudeAgent(Agent):
    def find(self) -> list[str] | None:
        override = os.environ.get("PRISM_CLAUDE_BIN")
        if override:
            return [override]
        found = shutil.which("claude")
        if found:
            return [found]
        candidates: list[str] = []
        appdata = os.environ.get("APPDATA")
        local = os.environ.get("LOCALAPPDATA")
        # The desktop app keeps its own copy; its folder has moved between app versions.
        for root, pattern in (
            (appdata, os.path.join("Claude", "claude-code", "*", "*", "claude.exe")),
            (local, os.path.join("Claude-Data", "*", "claude-code", "*", "*", "claude.exe")),
            (
                local,
                os.path.join(
                    "Packages",
                    "Claude_*",
                    "LocalCache",
                    "Roaming",
                    "Claude",
                    "claude-code",
                    "*",
                    "*",
                    "claude.exe",
                ),
            ),
        ):
            if root:
                candidates += glob.glob(os.path.join(root, pattern))
        candidates += glob.glob(os.path.expanduser("~/.local/bin/claude*"))
        existing = [c for c in candidates if os.path.isfile(c)]
        return [max(existing, key=os.path.getmtime)] if existing else None

    def version(self, base: list[str]) -> tuple[str | None, bool | None]:
        out = _run_text([*base, "--version"], 15)
        version = out.stdout.strip().splitlines()[0][:60] if out and out.stdout.strip() else None
        logged: bool | None = None
        auth = _run_text([*base, "auth", "status"])
        if auth:
            try:
                value = json.loads(auth.stdout).get("loggedIn")
                logged = value if isinstance(value, bool) else None
            except (ValueError, AttributeError):
                pass
        return version, logged

    def command(
        self, base: list[str], model: str, turns: int, directory: Path, task: str = ""
    ) -> list[str]:
        mcp = directory / ".mcp.json"  # only the With PRISM copy has one
        tools = CLAUDE_TOOLS + (" mcp__prism" if mcp.is_file() else "")
        command = [
            *base,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            str(turns),
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            tools,
            "--setting-sources",
            "project",
            *(["--mcp-config", str(mcp)] if mcp.is_file() else []),
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        return command + (["--model", model] if model else [])

    def stream(self) -> ClaudeStream:
        return ClaudeStream()


class CodexAgent(Agent):
    def find(self) -> list[str] | None:
        override = os.environ.get("PRISM_CODEX_BIN")
        if override:
            return [override]
        found = shutil.which("codex")
        return [found] if found else None

    def version(self, base: list[str]) -> tuple[str | None, bool | None]:
        out = _run_text([*base, "--version"], 15)
        version = out.stdout.strip().splitlines()[0][:60] if out and out.stdout.strip() else None
        status = _run_text([*base, "login", "status"])
        return version, (status.returncode == 0) if status else None

    def command(
        self, base: list[str], model: str, turns: int, directory: Path, task: str = ""
    ) -> list[str]:
        command = [
            *base,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(directory),
        ]
        if os.name == "nt":
            # The elevated Windows sandbox re-checks ACLs on every run and fails while the Codex app
            # holds its runtime open ("setup refresh had errors"); the restricted-token one does not.
            command += ["-c", 'windows.sandbox="unelevated"']
        if (directory / ".codex").is_dir():
            # Codex reads project .codex/ only for a trusted project, so the With copy trusts itself
            # and PRISM's MCP server is also given on the command line, which needs no trust.
            key = str(directory).lower() if os.name == "nt" else str(directory)
            command += [
                "-c",
                f"projects.'{key}'.trust_level=\"trusted\"",
                "-c",
                f"mcp_servers.prism.command={json.dumps(Path(sys.executable).as_posix())}",
                "-c",
                'mcp_servers.prism.args=["-m", "prism", "mcp"]',
                "-c",
                f"mcp_servers.prism.env.PYTHONPATH={json.dumps(_PACKAGE_ROOT)}",
                "-c",
                "mcp_servers.prism.startup_timeout_sec=20",
            ]
        if _only_prism_hooks(directory / ".codex" / "hooks.json"):
            # Codex asks the user to approve project hooks. These are the ones `prism init` just
            # wrote in a disposable copy, so approval is skipped for this run only, and only
            # when every hook in the file is a `prism hook` command.
            command.insert(command.index("--cd"), "--dangerously-bypass-hook-trust")
        return command + (["-m", model] if model else []) + ["-"]

    def stream(self) -> CodexStream:
        return CodexStream()


class AntigravityAgent(Agent):
    """The Antigravity CLI (`agy`) in print mode.

    Headless runs honor the user's saved permission rules and cannot prompt, so file reads,
    searches and edits work and shell commands are denied. Both arms get the same limits."""

    def find(self) -> list[str] | None:
        override = os.environ.get("PRISM_AGY_BIN")
        if override:
            return [override]
        found = shutil.which("agy")
        if found:
            return [found]
        fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
        return [str(fallback)] if fallback.is_file() else None

    def version(self, base: list[str]) -> tuple[str | None, bool | None]:
        out = _run_text([*base, "--version"], 15)
        text = out.stdout.strip().splitlines()[0][:60] if out and out.stdout.strip() else None
        return text, None

    def command(
        self, base: list[str], model: str, turns: int, directory: Path, task: str = ""
    ) -> list[str]:
        command = [
            *base,
            f"--print={task}{_AGY_NOTE}",
            "--output-format",
            "stream-json",
            "--mode",
            "accept-edits",
        ]
        return command + (["--model", model] if model else [])

    def stream(self) -> AntigravityStream:
        return AntigravityStream()


AGENTS: dict[str, Agent] = {
    "claude": ClaudeAgent("claude", "Claude Code", init_agent="claude-code"),
    "codex": CodexAgent("codex", "Codex", init_agent="codex"),
    "antigravity": AntigravityAgent(
        "antigravity", "Antigravity", init_agent="antigravity", stdin_prompt=False
    ),
}


# --- the runner ---------------------------------------------------------------------------


class LiveRunner:
    def __init__(
        self, root: Path, cache: Path, commands: dict[str, list[str]] | None = None
    ) -> None:
        self.root = root.resolve()
        self.cache = cache
        self._commands = commands or {}
        self._lock = threading.Lock()
        self._run: dict[str, Any] | None = None
        self._cancel = threading.Event()
        self._finish_manual = threading.Event()
        self._manual_before: dict[str, dict[str, bytes] | None] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._status_cache: tuple[float, list[dict[str, Any]]] | None = None
        try:
            saved = json.loads((cache / "last-run.json").read_text(encoding="utf-8"))
            if isinstance(saved, dict) and isinstance(saved.get("arms"), dict):
                if saved.get("state") in ACTIVE:
                    saved.update(
                        state="interrupted",
                        error="The server restarted before this run finished; it was not rerun",
                    )
                self._run = saved
        except (OSError, ValueError):
            pass

    # --- agents ---------------------------------------------------------------------------

    def base_command(self, agent_id: str) -> list[str] | None:
        return self._commands.get(agent_id) or AGENTS[agent_id].find()

    def is_manual(self, agent: Agent) -> bool:
        """Antigravity runs headless through `agy`; without it the user runs it by hand."""
        return agent.manual or (agent.id == "antigravity" and self.base_command(agent.id) is None)

    def agents(self) -> list[dict[str, Any]]:
        """Each agent's availability. Checked in parallel and kept for 30 seconds."""
        now = time.monotonic()
        if self._status_cache and now - self._status_cache[0] < 30:
            return self._status_cache[1]
        rows: dict[str, dict[str, Any]] = {}

        def check(agent: Agent) -> None:
            base = self.base_command(agent.id)
            version, logged = agent.version(base) if base else (None, None)
            rows[agent.id] = {
                "id": agent.id,
                "name": agent.name,
                "mode": "manual" if self.is_manual(agent) else "live",
                "found": base is not None,
                "version": version,
                "logged_in": logged,
            }

        threads = [threading.Thread(target=check, args=(a,)) for a in AGENTS.values()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        result = [rows[a] for a in AGENTS]
        self._status_cache = (now, result)
        return result

    def status(self) -> dict[str, Any]:
        return {"agents": self.agents(), "running": self.running()}

    def running(self) -> bool:
        with self._lock:
            return bool(self._run and self._run["state"] in ACTIVE)

    # --- control --------------------------------------------------------------------------

    def start(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise UserError("Expected a JSON object")
        task = body.get("task")
        if not isinstance(task, str) or not task.strip() or len(task) > 12000:
            raise UserError("Enter a task between 1 and 12000 characters")
        agent_id = body.get("agent", "claude")
        if agent_id not in AGENTS:
            raise UserError("Choose Claude Code, Codex or Antigravity")
        agent = AGENTS[agent_id]
        check = body.get("check_command") or ""
        if not isinstance(check, str) or len(check) > 1000 or "\n" in check:
            raise UserError("The check command must be a single line of at most 1000 characters")
        model = body.get("model") or ""
        if not isinstance(model, str) or (model and not _MODEL.fullmatch(model)):
            raise UserError("Model contains unsupported characters")
        turns = body.get("max_turns", 30)
        if type(turns) is not int or not 1 <= turns <= 100:
            raise UserError("Maximum turns must be between 1 and 100")
        minutes = body.get("timeout_minutes", 15)
        if type(minutes) is not int or not 1 <= minutes <= 60:
            raise UserError("Timeout must be between 1 and 60 minutes")
        base = self.base_command(agent_id)
        if base is None and not self.is_manual(agent):
            raise UserError(
                f"{agent.name} was not found on this computer. Install it and log in, then try again"
            )
        with self._lock:
            if self._run and self._run["state"] in ACTIVE:
                raise UserError("A live comparison is already running for this project")
            self._cancel.clear()
            self._finish_manual.clear()
            self._run = {
                "id": uuid.uuid4().hex,
                "state": "preparing",
                "agent": agent_id,
                "agent_name": agent.name,
                "manual": self.is_manual(agent),
                "task": task.strip(),
                "check_command": check.strip(),
                "model": model,
                "started": time.time(),
                "finished": None,
                "error": None,
                "preparation": None,
                "arms": {arm: _empty_arm() for arm in ARMS},
                "verdict": None,
            }
            run = self._run
            try:
                write_json(self.cache / "last-run.json", run)
            except OSError as exc:
                self._run = None
                raise UserError(f"Could not save the comparison before starting: {exc}") from exc
        threading.Thread(
            target=self._execute, args=(run, agent, base, turns, minutes * 60), daemon=True
        ).start()
        return self.snapshot() or {}

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        self._finish_manual.set()
        for process in list(self._processes.values()):
            _kill(process)
        return self.snapshot() or {}

    def finish_manual(self, allow_unchanged: bool = False) -> dict[str, Any]:
        """Antigravity hand-off: both folders have been worked on; check and compare them."""
        with self._lock:
            if not self._run or self._run["state"] != "awaiting_manual":
                raise UserError("Nothing is waiting for a manual result")
            if not allow_unchanged:
                directories = self._run["preparation"]["arms"]
                unchanged = [
                    arm
                    for arm in ARMS
                    if self._manual_before.get(arm) is not None
                    and _snapshot(Path(directories[arm])) == self._manual_before[arm]
                ]
                if unchanged:
                    names = ", ".join(
                        "Without PRISM" if a == "without" else "With PRISM" for a in unchanged
                    )
                    raise UserError(
                        f"No source changes detected in {names}. Open each folder in Antigravity "
                        "and finish the task first. For a task that intentionally needs no edits, "
                        "select the no-source-changes option."
                    )
        self._finish_manual.set()
        return self.snapshot() or {}

    def snapshot(self, since_without: int = 0, since_with: int = 0) -> dict[str, Any] | None:
        with self._lock:
            if self._run is None:
                return None
            run = {k: v for k, v in self._run.items() if k != "arms"}
            offsets = {"without": since_without, "with": since_with}
            arms = {}
            for name, arm in self._run["arms"].items():
                view = {k: v for k, v in arm.items() if k != "events"}
                view["event_count"] = len(arm["events"])
                view["events"] = arm["events"][max(0, offsets[name]) :]
                arms[name] = view
            run["arms"] = arms
            copy: dict[str, Any] = json.loads(json.dumps(run))
            return copy

    # --- history --------------------------------------------------------------------------

    def history(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted((self.cache / "runs").glob("*.json"), reverse=True)[:100]:
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
                arms = run["arms"]
                rows.append(
                    {
                        "id": run["id"],
                        "task": run["task"],
                        "agent": run.get("agent", "claude"),
                        "agent_name": run.get("agent_name", "Claude Code"),
                        "state": run["state"],
                        "started": run["started"],
                        "check_command": run.get("check_command", ""),
                        "verdict": run.get("verdict"),
                        "without": {
                            k: arms["without"].get(k)
                            for k in ("usage", "cost_usd", "duration_seconds", "commands_run")
                        },
                        "with": {
                            k: arms["with"].get(k)
                            for k in ("usage", "cost_usd", "duration_seconds", "commands_run")
                        },
                    }
                )
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(rows, key=lambda row: row["started"], reverse=True)

    def saved_run(self, ident: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise UserError("Invalid run ID")
        try:
            value: dict[str, Any] = json.loads(
                (self.cache / "runs" / f"{ident}.json").read_text(encoding="utf-8")
            )
            return value
        except (OSError, ValueError) as exc:
            raise NotFoundError("Run not found") from exc

    # --- orchestration --------------------------------------------------------------------

    def _update(self, run: dict[str, Any], **values: Any) -> None:
        with self._lock:
            run.update(values)
            write_json(self.cache / "last-run.json", run)

    def _finish(self, run: dict[str, Any], state: str, error: str | None = None) -> None:
        with self._lock:
            run.update(state=state, error=error, finished=time.time())
            copy: dict[str, Any] = json.loads(json.dumps(run))
        write_json(self.cache / "last-run.json", copy)
        if run.get("verdict") is not None:
            write_json(self.cache / "runs" / f"{run['id']}.json", copy)

    def _execute(
        self,
        run: dict[str, Any],
        agent: Agent,
        base: list[str] | None,
        max_turns: int,
        timeout: float,
    ) -> None:
        try:
            self._execute_inner(run, agent, base, max_turns, timeout)
        except Exception as exc:
            # An unexpected diff, filesystem or verifier error must not leave an
            # active comparison stuck forever in one of several project panels.
            try:
                self._finish(run, "failed", f"Comparison failed: {exc}")
            except OSError:
                with self._lock:
                    run.update(
                        state="failed",
                        error=f"Comparison failed and its result could not be saved: {exc}",
                        finished=time.time(),
                    )

    def _execute_inner(
        self,
        run: dict[str, Any],
        agent: Agent,
        base: list[str] | None,
        max_turns: int,
        timeout: float,
    ) -> None:
        from prism.viewer.sandboxes import prepare_pair

        try:
            preparation = prepare_pair(self.root, run["task"])
            directory = Path(preparation["arms"]["without"]).parent
            with_dir = Path(preparation["arms"]["with"])
            config_home = directory / "config"
            config_home.mkdir(exist_ok=True)
            (directory / "config-empty").mkdir(exist_ok=True)
            self._install_integration(with_dir, config_home, agent)
            self._update(run, preparation=preparation)
        except Exception as exc:  # preparation failures are reported, never retried silently
            self._finish(run, "failed", f"Preparing the two copies failed: {exc}")
            return
        if self._cancel.is_set():
            self._finish(run, "cancelled")
            return
        dirs = {"without": Path(preparation["arms"]["without"]), "with": with_dir}
        before = {arm: _snapshot(path) for arm, path in dirs.items()}
        manual = self.is_manual(agent)
        if manual:
            self._manual_before = before
            self._update(
                run,
                manual_launch={
                    arm: self._manual_launch(
                        dirs[arm],
                        directory / ("config" if arm == "with" else "config-empty"),
                        arm == "with",
                    )
                    for arm in ARMS
                },
            )
            self._manual(run, dirs)
        else:
            assert base is not None
            envs = {
                "without": self._env(directory / "config-empty", with_prism=False),
                "with": self._env(config_home, with_prism=True),
            }
            self._update(run, state="running")
            threads = [
                threading.Thread(
                    target=self._run_arm,
                    args=(run, arm, agent, base, dirs[arm], envs[arm], max_turns, timeout),
                    daemon=True,
                )
                for arm in ARMS
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        if self._cancel.is_set():
            self._finish(run, "cancelled")
            return
        self._update(run, state="checking")
        for arm in ARMS:
            if self._cancel.is_set():
                self._finish(run, "cancelled")
                return
            patch, changed, added, removed = _changes(before[arm], dirs[arm])
            check = None
            if run["check_command"]:
                check_id = f"verification-{arm}"
                self._push(
                    run,
                    arm,
                    {
                        "kind": "terminal_start",
                        "id": check_id,
                        "command": run["check_command"],
                        "phase": "verification",
                    },
                )
                check = self._check(run["check_command"], dirs[arm])
                self._push(
                    run,
                    arm,
                    {
                        "kind": "terminal_end",
                        "id": check_id,
                        "ok": check["passed"],
                        "output": check["output"],
                        "phase": "verification",
                    },
                )
            with self._lock:
                run["arms"][arm].update(
                    patch=patch,
                    files_changed=changed,
                    lines_added=added,
                    lines_removed=removed,
                    check=check,
                )
        if self._cancel.is_set():
            self._finish(run, "cancelled")
            return
        with self._lock:
            run["verdict"] = compare(run["arms"], bool(run["check_command"]))
            if manual:
                # The hand-off interval is human workflow time, not measured agent execution.
                run["verdict"]["time_saving_pct"] = None
                run["verdict"]["commands_saving_pct"] = None
        failed = [a for a in ARMS if run["arms"][a]["state"] != "completed"]
        self._finish(run, "failed" if failed else "completed")

    def _manual_launch(self, directory: Path, config_home: Path, with_prism: bool) -> str:
        """Launch instructions carry the same consent and PATH setup as managed runs."""
        env = self._env(config_home, with_prism)
        if os.name == "nt":

            def quote(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            return "\n".join(
                [
                    f"$env:PRISM_CONFIG_HOME = {quote(str(config_home))}",
                    f"$env:PATH = {quote(env['PATH'])}",
                    f"Set-Location -LiteralPath {quote(str(directory))}",
                    "antigravity .",
                ]
            )
        return "\n".join(
            [
                f"export PRISM_CONFIG_HOME={shlex.quote(str(config_home))}",
                f"export PATH={shlex.quote(env['PATH'])}",
                f"cd -- {shlex.quote(str(directory))}",
                "antigravity .",
            ]
        )

    def _manual(self, run: dict[str, Any], dirs: dict[str, Path]) -> None:
        """Antigravity: wait for the person to do the task in both folders, then carry on."""
        with self._lock:
            run["state"] = "awaiting_manual"
            for arm in ARMS:
                run["arms"][arm]["state"] = "manual"
                run["arms"][arm]["started"] = time.time()
                run["arms"][arm]["events"].append(
                    {
                        "kind": "info",
                        "t": 0,
                        "text": f"Open this folder in Antigravity and give it the task: {dirs[arm]}",
                    }
                )
        self._finish_manual.wait()
        with self._lock:
            for arm in ARMS:
                if run["arms"][arm]["state"] == "manual":
                    state = run["arms"][arm]
                    state.update(state="completed", finished=time.time())
                    state["duration_seconds"] = state["finished"] - state["started"]

    def _install_integration(self, with_dir: Path, config_home: Path, agent: Agent) -> None:
        """Real `prism init` for the agent in the With copy only: hooks and MCP, no git hooks."""
        env = self._env(config_home, with_prism=True)
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "prism",
                "init",
                "--root",
                str(with_dir),
                "--agent",
                agent.init_agent,
                "--hooks",
                "--mcp",
                "--no-git-hooks",
                "--no-scan",
                "--yes",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if process.returncode:
            raise UserError(f"prism init failed in the With PRISM copy: {process.stderr.strip()}")
        self._require_connected(with_dir, agent, env)

    def _require_connected(self, with_dir: Path, agent: Agent, env: dict[str, str]) -> None:
        """The With copy must start every run with PRISM's hook and MCP connected, or not run."""
        missing: list[str] = []
        if agent.init_agent == "claude-code":
            mcp = with_dir / ".mcp.json"
            if not mcp.is_file() or '"prism"' not in mcp.read_text(encoding="utf-8", errors="replace"):
                missing.append("MCP server (.mcp.json)")
            settings = with_dir / ".claude" / "settings.json"
            if not settings.is_file() or "prism" not in settings.read_text(encoding="utf-8", errors="replace"):
                missing.append("hooks (.claude/settings.json)")
        probe = subprocess.run(
            ["prism", "--version"], capture_output=True, text=True, env=env, timeout=60, shell=os.name == "nt"
        )
        if probe.returncode:
            missing.append("`prism` command on the agent's PATH")
        if missing:
            raise UserError("PRISM is not connected in the With PRISM copy: " + ", ".join(missing))

    def _env(self, config_home: Path, with_prism: bool) -> dict[str, str]:
        env = dict(os.environ)
        env["PRISM_CONFIG_HOME"] = str(config_home)
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
        # The baseline must not be able to find PRISM; the With copy must (its hooks and MCP run `prism`).
        parts = [p for p in parts if not shutil.which("prism", path=p)]
        if with_prism:
            parts.insert(0, str(_prism_shim(config_home / "bin")))
        env["PATH"] = os.pathsep.join(parts)
        return env

    def _check(self, command: str, directory: Path) -> dict[str, Any]:
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        key = f"verification-{threading.get_ident()}"
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            self._processes[key] = process
            if self._cancel.is_set():
                _kill(process)
            stdout, stderr = process.communicate(timeout=300)
            output = stdout + stderr
            empty_suite = bool(re.search(r"\bRan 0 tests?\b", output))
            if empty_suite:
                output = (
                    "Verification did not discover any tests; quality is not verified.\n" + output
                )
            return {
                "ran": True,
                "passed": process.returncode == 0 and not empty_suite,
                "exit_code": process.returncode,
                "output": output[-4000:],
                "seconds": time.monotonic() - started,
            }
        except subprocess.TimeoutExpired:
            if process is not None:
                _kill(process)
                process.communicate(timeout=10)
            return {
                "ran": True,
                "passed": False,
                "exit_code": None,
                "output": "Check timed out after 300 seconds",
                "seconds": 300.0,
            }
        except OSError as exc:
            return {
                "ran": False,
                "passed": False,
                "exit_code": None,
                "output": str(exc),
                "seconds": 0.0,
            }
        finally:
            self._processes.pop(key, None)

    def _push(self, run: dict[str, Any], arm: str, event: dict[str, Any]) -> None:
        with self._lock:
            events = run["arms"][arm]["events"]
            if len(events) < MAX_EVENTS:
                event["t"] = round(time.time() - run["started"], 2)
                events.append(event)
            if event.get("kind") == "terminal_start" and event.get("phase") != "verification":
                run["arms"][arm]["commands_run"] += 1

    def _run_arm(
        self,
        run: dict[str, Any],
        arm: str,
        agent: Agent,
        base: list[str],
        directory: Path,
        env: dict[str, str],
        max_turns: int,
        timeout: float,
    ) -> None:
        state = run["arms"][arm]
        command = agent.command(base, run["model"], max_turns, directory, run["task"])
        with self._lock:
            state.update(state="running", started=time.time())
        started = time.monotonic()
        stream = agent.stream()
        stderr_tail: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=env,
                stdin=subprocess.PIPE if agent.stdin_prompt else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            with self._lock:
                state.update(state="failed", error=f"Could not start {agent.name}: {exc}")
            return
        self._processes[arm] = process
        assert process.stdout and process.stderr
        stderr = process.stderr
        if process.stdin:
            try:
                process.stdin.write(run["task"])
                process.stdin.close()
            except OSError:
                pass
        threading.Thread(
            target=lambda: stderr_tail.extend(stderr.readlines()[-20:]), daemon=True
        ).start()
        watchdog = threading.Timer(timeout, lambda: _kill(process))
        watchdog.start()
        done = False
        failure: str | None = None
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                update = stream.feed(message)
                for event in update.events:
                    self._push(run, arm, event)
                with self._lock:
                    if update.usage is not None and (update.final or not state["usage_final"]):
                        state["usage"] = update.usage
                        state["usage_final"] = state["usage_final"] or update.final
                    if update.cost is not None:
                        state["cost_usd"] = update.cost
                    if update.turns is not None:
                        state["turns"] = update.turns
                    if update.text is not None:
                        state["final_text"] = update.text
                done = done or update.done
                failure = update.failed or failure
            process.wait()
        finally:
            watchdog.cancel()
            self._processes.pop(arm, None)
        seconds = time.monotonic() - started
        with self._lock:
            state.update(duration_seconds=round(seconds, 2), finished=time.time())
            if self._cancel.is_set():
                state["state"] = "cancelled"
            elif not done:
                tail = "".join(stderr_tail).strip()
                state.update(
                    state="failed",
                    error="Timed out"
                    if seconds >= timeout
                    else (failure or tail[-500:] or f"{agent.name} exited without a result"),
                )
            elif failure:
                state.update(state="failed", error=failure)
            else:
                state["state"] = "completed"
