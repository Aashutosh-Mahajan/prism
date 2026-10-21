"""Live paired runs: one task through Claude Code in two disposable copies.

Without PRISM gets a plain source copy. With PRISM gets the same copy plus the real PRISM index and
its Claude Code hooks. Both runs happen at once; their events and token counters are streamed to the
dashboard, and an optional check command is run in each finished copy to see whether the result
is still correct. Folder copies are not an OS sandbox; the agent is limited to its own folder only by
Claude Code's own permission rules.
"""

from __future__ import annotations

import difflib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from prism.core.errors import UserError
from prism.writers.json_writer import write_json

ARMS = ("without", "with")
MAX_EVENTS = 3000
MAX_TEXT = 1500
SNAPSHOT_FILE_LIMIT = 512 * 1024
SNAPSHOT_TOTAL_LIMIT = 64 * 1024 * 1024
# Files PRISM's own integration adds or an agent run produces. They are not part of the solution.
_NOISE_DIRS = {
    ".git",
    ".aicontext",
    ".claude",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
_NOISE_FILES = {".mcp.json"}
DEFAULT_TOOLS = (
    "Read Glob Grep Edit Write Bash(python:*) Bash(pytest:*) Bash(prism:*) Bash(npm test:*)"
)
_MODEL = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,80}$")


def find_agent() -> list[str] | None:
    """Locate Claude Code: PRISM_CLAUDE_BIN, PATH, the desktop app's copy, or ~/.local/bin."""
    override = os.environ.get("PRISM_CLAUDE_BIN")
    if override:
        return [override]
    found = shutil.which("claude")
    if found:
        return [found]
    candidates: list[str] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates += glob.glob(
            os.path.join(appdata, "Claude", "claude-code", "*", "*", "claude.exe")
        )
    candidates += glob.glob(os.path.expanduser("~/.local/bin/claude*"))
    existing = [c for c in candidates if os.path.isfile(c)]
    return [max(existing, key=os.path.getmtime)] if existing else None


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
    return (
        value
        if len(value) <= limit
        else value[:limit] + f" … ({len(value) - limit} more characters)"
    )


def _summarize_tool(name: str, data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("command", "file_path", "path", "pattern", "url", "description"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return _clip(value, 300)
    return ""


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


def _changes(before: dict[str, bytes] | None, directory: Path) -> tuple[str, list[str]]:
    """Unified diff of text files and the list of changed paths; empty when no snapshot exists."""
    if before is None:
        return "Source tree too large to diff.", []
    after = _snapshot(directory)
    if after is None:
        return "Source tree too large to diff.", []
    changed: list[str] = []
    chunks: list[str] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        changed.append(path)
        try:
            a = (old or b"").decode("utf-8").splitlines(keepends=True) if old is not None else []
            b = (new or b"").decode("utf-8").splitlines(keepends=True) if new is not None else []
        except UnicodeDecodeError:
            chunks.append(f"Binary file changed: {path}\n")
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    a,
                    b,
                    fromfile="/dev/null" if old is None else f"a/{path}",
                    tofile="/dev/null" if new is None else f"b/{path}",
                )
            )
        )
    return _clip("".join(chunks), 60000), changed


def _empty_arm() -> dict[str, Any]:
    return {
        "state": "waiting",
        "events": [],
        "usage": None,
        "usage_final": False,
        "turns": None,
        "duration_seconds": None,
        "cost_usd": None,
        "final_text": "",
        "error": None,
        "patch": "",
        "files_changed": [],
        "check": None,
    }


def usage_totals(raw: dict[str, Any] | None) -> dict[str, int] | None:
    """Claude Code usage counters; cache reads and writes are input the model processed."""
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


def compare(arms: dict[str, dict[str, Any]], check_given: bool) -> dict[str, Any]:
    """Token savings and whether the solution stayed as good. Never invents a missing number."""
    without, with_ = arms["without"], arms["with"]

    def pct(key: str) -> float | None:
        a = (without["usage"] or {}).get(key) if key != "cost_usd" else without["cost_usd"]
        b = (with_["usage"] or {}).get(key) if key != "cost_usd" else with_["cost_usd"]
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not a:
            return None
        return (a - b) / a * 100

    finished = all(arm["state"] == "completed" for arm in arms.values())
    if not finished:
        quality = "incomplete"
    elif not check_given:
        quality = "unverified"
    else:
        a = bool((without["check"] or {}).get("passed"))
        b = bool((with_["check"] or {}).get("passed"))
        quality = "same" if a and b else "degraded" if a else "better" if b else "both_failed"
    return {
        "quality": quality,
        "token_saving_pct": pct("total_tokens") if finished else None,
        "input_saving_pct": pct("input_total") if finished else None,
        "output_saving_pct": pct("output_tokens") if finished else None,
        "cost_saving_pct": pct("cost_usd") if finished else None,
        "identical_patch": bool(finished and without["patch"] == with_["patch"]),
    }


class LiveRunner:
    def __init__(self, root: Path, cache: Path, agent: list[str] | None = None) -> None:
        self.root = root.resolve()
        self.cache = cache
        self._agent = agent
        self._lock = threading.Lock()
        self._run: dict[str, Any] | None = None
        self._cancel = threading.Event()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        try:
            saved = json.loads((cache / "last-run.json").read_text(encoding="utf-8"))
            if isinstance(saved, dict) and isinstance(saved.get("arms"), dict):
                if saved.get("state") in ("preparing", "running", "checking"):
                    saved.update(
                        state="interrupted",
                        error="The server restarted before this run finished; it was not rerun",
                    )
                self._run = saved
        except (OSError, ValueError):
            pass

    # --- public API ---------------------------------------------------------------------

    def agent(self) -> list[str] | None:
        return self._agent or find_agent()

    def status(self) -> dict[str, Any]:
        agent = self.agent()
        logged_in: bool | None = None
        version = None
        if agent:
            try:
                out = subprocess.run(
                    [*agent, "--version"], capture_output=True, text=True, timeout=15
                )
                version = out.stdout.strip().splitlines()[0][:60] if out.stdout.strip() else None
                auth = subprocess.run(
                    [*agent, "auth", "status"], capture_output=True, text=True, timeout=20
                )
                value = json.loads(auth.stdout).get("loggedIn")
                logged_in = value if isinstance(value, bool) else None
            except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
                pass
        return {
            "agent_found": agent is not None,
            "agent_version": version,
            "logged_in": logged_in,
            "running": self.running(),
        }

    def running(self) -> bool:
        with self._lock:
            return bool(self._run and self._run["state"] in ("preparing", "running", "checking"))

    def start(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise UserError("Expected a JSON object")
        task = body.get("task")
        if not isinstance(task, str) or not task.strip() or len(task) > 12000:
            raise UserError("Enter a task between 1 and 12000 characters")
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
        agent = self.agent()
        if agent is None:
            raise UserError(
                "Claude Code was not found. Install it, or set PRISM_CLAUDE_BIN to its executable"
            )
        with self._lock:
            if self._run and self._run["state"] in ("preparing", "running", "checking"):
                raise UserError("A live comparison is already running")
            self._cancel.clear()
            self._run = {
                "id": uuid.uuid4().hex,
                "state": "preparing",
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
        threading.Thread(
            target=self._execute, args=(run, agent, turns, minutes * 60), daemon=True
        ).start()
        return self.snapshot() or {}

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        for process in list(self._processes.values()):
            _kill(process)
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

    # --- orchestration ------------------------------------------------------------------

    def _update(self, run: dict[str, Any], **values: Any) -> None:
        with self._lock:
            run.update(values)

    def _finish(self, run: dict[str, Any], state: str, error: str | None = None) -> None:
        with self._lock:
            run.update(state=state, error=error, finished=time.time())
        write_json(self.cache / "last-run.json", self._persistable(run))

    def _persistable(self, run: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            copy: dict[str, Any] = json.loads(json.dumps(run))
            return copy

    def _execute(
        self, run: dict[str, Any], agent: list[str], max_turns: int, timeout: float
    ) -> None:
        from prism.viewer.sandboxes import prepare_pair

        try:
            preparation = prepare_pair(self.root, run["task"])
            directory = Path(preparation["arms"]["without"]).parent
            with_dir = Path(preparation["arms"]["with"])
            config_home = directory / "config"
            config_home.mkdir(exist_ok=True)
            (directory / "config-empty").mkdir(exist_ok=True)
            self._install_integration(with_dir, config_home)
            self._update(run, preparation=preparation)
        except Exception as exc:  # preparation failures are reported, never retried silently
            self._finish(run, "failed", f"Preparing the two copies failed: {exc}")
            return
        if self._cancel.is_set():
            self._finish(run, "cancelled")
            return
        dirs = {"without": Path(preparation["arms"]["without"]), "with": with_dir}
        envs = {
            "without": self._env(directory / "config-empty", with_prism=False),
            "with": self._env(config_home, with_prism=True),
        }
        before = {arm: _snapshot(path) for arm, path in dirs.items()}
        self._update(run, state="running")
        threads = [
            threading.Thread(
                target=self._run_arm,
                args=(run, arm, agent, dirs[arm], envs[arm], max_turns, timeout),
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
            patch, changed = _changes(before[arm], dirs[arm])
            check = self._check(run["check_command"], dirs[arm]) if run["check_command"] else None
            with self._lock:
                run["arms"][arm].update(patch=patch, files_changed=changed, check=check)
        with self._lock:
            run["verdict"] = compare(run["arms"], bool(run["check_command"]))
        failed = [a for a in ARMS if run["arms"][a]["state"] != "completed"]
        self._finish(run, "completed" if not failed else "failed")

    def _install_integration(self, with_dir: Path, config_home: Path) -> None:
        """Real `prism init` for Claude Code in the With copy only; hooks, no MCP, no git hooks."""
        env = dict(os.environ, PRISM_CONFIG_HOME=str(config_home))
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "prism",
                "init",
                "--root",
                str(with_dir),
                "--agent",
                "claude-code",
                "--hooks",
                "--no-mcp",
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

    def _env(self, config_home: Path, with_prism: bool) -> dict[str, str]:
        env = dict(os.environ)
        env["PRISM_CONFIG_HOME"] = str(config_home)
        scripts = str(Path(sys.executable).parent)
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
        # The baseline must not be able to find PRISM; the With copy must (its hooks run `prism`).
        parts = [p for p in parts if not shutil.which("prism", path=p)]
        env["PATH"] = os.pathsep.join(([scripts] if with_prism else []) + parts)
        return env

    def _check(self, command: str, directory: Path) -> dict[str, Any]:
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
        started = time.monotonic()
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                env=env,
            )
            output = (process.stdout + process.stderr)[-4000:]
            return {
                "ran": True,
                "passed": process.returncode == 0,
                "exit_code": process.returncode,
                "output": output,
                "seconds": time.monotonic() - started,
            }
        except subprocess.TimeoutExpired:
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

    def _push(self, run: dict[str, Any], arm: str, event: dict[str, Any]) -> None:
        with self._lock:
            events = run["arms"][arm]["events"]
            if len(events) < MAX_EVENTS:
                event["t"] = round(time.time() - run["started"], 2)
                events.append(event)

    def _run_arm(
        self,
        run: dict[str, Any],
        arm: str,
        agent: list[str],
        directory: Path,
        env: dict[str, str],
        max_turns: int,
        timeout: float,
    ) -> None:
        state = run["arms"][arm]
        command = [
            *agent,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            DEFAULT_TOOLS,
            "--setting-sources",
            "project",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if run["model"]:
            command += ["--model", run["model"]]
        with self._lock:
            state["state"] = "running"
        started = time.monotonic()
        seen_messages: dict[str, dict[str, Any]] = {}
        stderr_tail: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            with self._lock:
                state.update(state="failed", error=f"Could not start Claude Code: {exc}")
            return
        self._processes[arm] = process
        assert process.stdin and process.stdout and process.stderr
        stderr = process.stderr
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
        result: dict[str, Any] | None = None
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    result = self._handle(run, arm, message, seen_messages) or result
            process.wait()
        finally:
            watchdog.cancel()
            self._processes.pop(arm, None)
        seconds = time.monotonic() - started
        with self._lock:
            state["duration_seconds"] = round(seconds, 2)
            if self._cancel.is_set():
                state["state"] = "cancelled"
            elif result is None:
                tail = "".join(stderr_tail).strip()
                timed_out = seconds >= timeout
                state.update(
                    state="failed",
                    error="Timed out"
                    if timed_out
                    else (tail[-500:] or "Claude Code exited without a result"),
                )
            elif result.get("is_error"):
                state.update(
                    state="failed",
                    error=_clip(result.get("result") or "Claude Code reported an error", 500),
                )
            else:
                state["state"] = "completed"

    def _handle(
        self,
        run: dict[str, Any],
        arm: str,
        message: dict[str, Any],
        seen: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        state = run["arms"][arm]
        kind = message.get("type")
        if kind == "system" and message.get("subtype") == "init":
            self._push(
                run,
                arm,
                {"kind": "info", "text": f"Started · model {message.get('model', 'unknown')}"},
            )
        elif kind == "assistant" and isinstance(message.get("message"), dict):
            body = message["message"]
            ident = body.get("id")
            if isinstance(ident, str) and isinstance(body.get("usage"), dict):
                seen[ident] = body["usage"]  # the last report for a message id is its total
                live = usage_totals(
                    {
                        key: sum(int(u.get(key) or 0) for u in seen.values())
                        for key in (
                            "input_tokens",
                            "cache_creation_input_tokens",
                            "cache_read_input_tokens",
                            "output_tokens",
                        )
                    }
                )
                with self._lock:
                    if not state["usage_final"]:
                        state["usage"] = live
            for block in body.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    self._push(run, arm, {"kind": "text", "text": _clip(block["text"])})
                elif block.get("type") == "tool_use":
                    name = str(block.get("name", "tool"))
                    self._push(
                        run,
                        arm,
                        {
                            "kind": "tool",
                            "name": name,
                            "text": _summarize_tool(name, block.get("input")),
                        },
                    )
        elif kind == "user" and isinstance(message.get("message"), dict):
            for block in message["message"].get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(
                            str(part.get("text", "")) for part in content if isinstance(part, dict)
                        )
                    self._push(
                        run,
                        arm,
                        {
                            "kind": "result",
                            "ok": not block.get("is_error"),
                            "text": _clip(content or "", 600),
                        },
                    )
        elif kind == "result":
            final = usage_totals(message.get("usage"))
            with self._lock:
                if final:
                    state["usage"], state["usage_final"] = final, True
                cost = message.get("total_cost_usd")
                state["cost_usd"] = cost if isinstance(cost, (int, float)) else None
                state["turns"] = message.get("num_turns")
                state["final_text"] = _clip(message.get("result") or "", 4000)
            return message
        return None
