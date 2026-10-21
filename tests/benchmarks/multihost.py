"""Parallel native benchmark across Codex, Claude Code and Antigravity, with and without PRISM.

    python -m tests.benchmarks.multihost prepare --output DIR [--reps 2]
    python -m tests.benchmarks.multihost run --output DIR [--workers 4] [--only HOST]
    python -m tests.benchmarks.multihost watch --output DIR     # live token counter
    python -m tests.benchmarks.multihost report --output DIR

Every session is one fresh agent in its own disposable copy of the frozen repository, scored by
the independent campaign checks, and measured only from the host's own usage records. Arms:
`baseline` (no PRISM), `cli` (instruction block + `prism` on PATH), `mcp` (+ the lean MCP
server), `hook` (+ the prompt hook), `hook_mcp` (hook and MCP). Existing subscription sign-ins
are reused; API keys are removed from every session's environment.

Isolation per host:
* Codex: one benchmark CODEX_HOME holding a copy of the ChatGPT sign-in, with every trial's
  project trust written before the run, so nothing in it changes while sessions run in parallel.
* Claude Code: `--setting-sources project` (no user hooks, plugins or settings),
  `--strict-mcp-config` (only the trial's MCP server, or none), no session persistence.
* Antigravity: its MCP list is user-level, so one temporary `prism` entry points at a dispatcher
  that starts the trial's PRISM server only where the trial enabled MCP and an empty server
  elsewhere; it is removed when the run ends.

Token fields are normalised to one schema (fresh input, cache read, cache write, output), plus a
cost-weighted equivalent (fresh + 0.1 x cache read + 1.25 x cache write + output) that compares
hosts whose caches differ. Compare arms within a host first; across hosts, compare the change
against that host's own baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from tests.benchmarks.campaign_run import (
    AROGYA_REV,
    COMMON,
    environment,
    git_archive,
    source_hashes,
    source_inventory,
)

ROOT = Path(__file__).resolve().parents[2]
AROGYA = Path("D:/Projects/Arogyatrack/ArogyaTrack")
TASKS = Path(__file__).with_name("campaign_confirmation_tasks.json")
HARD_TASKS = Path(__file__).with_name("campaign_hard_tasks.json")
CHECKS = Path(__file__).with_name("campaign_checks.py")
SEED = 20261021
ARMS = ("baseline", "cli", "mcp", "hook", "hook_mcp")
HOSTS = ("codex", "claude", "antigravity")
MODELS = {
    "codex": "gpt-6-luna",
    "claude": "claude-sonnet-5-5",
    "antigravity": "gemini-3.8-flash-medium",
}
INTEGRATION = {"codex": "codex", "claude": "claude-code", "antigravity": "antigravity"}
SESSION_TIMEOUT = 900
HOST_FAILURE_LIMIT = 5
MIN_FREE_BYTES = 3 * 1024**3  # 18 parallel copies of the repository need about 2 GB
# Cost weights relative to fresh input, a comparison proxy rather than prices: cache reads at
# 0.1x; Anthropic's 5-minute cache writes at 1.25x and 1-hour writes (what Claude Code uses) at 2x.
CACHE_READ_WEIGHT = 0.1
CACHE_WRITE_WEIGHT = 1.25
CACHE_WRITE_1H_WEIGHT = 2.0
ARM_NOTE = {
    "baseline": "Use normal local navigation without PRISM.\n",
    "cli": "Use the configured PRISM CLI for code navigation; no MCP or hooks are configured.\n",
}
AUTHORIZED = (
    "Requested edits are authorized inside this disposable repository. Do not alter permission "
    "policies.\n"
)
ENGINE_ENTRY = """\
import contextlib, io, json, os, sys, time
from pathlib import Path
ENGINE = {engine!r}
sys.path.insert(0, ENGINE)
for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
trial = Path(os.environ.get("PRISM_BENCH_TRIAL") or Path.cwd().parent)
os.environ["PRISM_CONFIG_HOME"] = str(trial / "config")
os.environ["PRISM_SEMANTIC"] = "0"
os.environ["PRISM_DAEMON"] = "0"
os.environ.setdefault("PRISM_MCP_PROFILE", "lean")
if sys.argv[1:2] == ["hook"]:
    from prism.hooks import entry
    raw = sys.stdin.read()
    sys.stdin = io.StringIO(raw)
    output = io.StringIO()
    os.environ["PRISM_HOOK_NO_EXIT"] = "1"
    with contextlib.redirect_stdout(output):
        entry.run_hook(sys.argv[2], sys.argv[3:])
    text = output.getvalue()
    try:
        payload = json.loads(raw or "{{}}")
    except ValueError:
        payload = {{"unparsed": raw[:2000]}}
    with (trial / "logs" / "hooks.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({{"hook": sys.argv[2], "payload": payload, "output": text, "timestamp": time.time()}}) + "\\n")
    sys.stdout.write(text)
else:
    from prism.entry import main
    main()
"""
# Antigravity starts user-level MCP servers in the session's workspace: serve PRISM only there.
AGY_DISPATCH = """\
import os, sys
from pathlib import Path
trial = Path.cwd().parent
if (trial / "mcp-enabled").is_file():
    os.environ["PRISM_BENCH_TRIAL"] = str(trial)
    sys.argv = [sys.argv[0], "mcp"]
    exec(compile(Path({entry!r}).read_text(encoding="utf-8"), {entry!r}, "exec"))
else:
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server
    Server("prism").run("stdio")
"""
_LOCK = threading.Lock()


# --- preparation ---------------------------------------------------------------------------------


def _copy_engine(target: Path) -> str:
    shutil.copytree(
        ROOT / "prism", target / "prism", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    digest = hashlib.sha256()
    for path in sorted((target / "prism").rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(target).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def trial_dir(base: Path, host: str, task: str, arm: str, rep: int) -> Path:
    return base / "runs" / host / f"{task}-{arm}-{rep}"


def _codex_home(base: Path, trials: list[Path]) -> None:
    home = base / "codex-home"
    home.mkdir()
    original = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    credentials = json.loads(original.read_text(encoding="utf-8"))
    if credentials.get("auth_mode") != "chatgpt" or not credentials.get("tokens"):
        raise ValueError("existing ChatGPT sign-in is required; no API key fallback")
    credentials["OPENAI_API_KEY"] = None
    (home / "auth.json").write_text(json.dumps(credentials), encoding="utf-8")
    trust = "".join(
        f'\n[projects.{json.dumps(str((trial / "repo").resolve()).lower())}]\ntrust_level = "trusted"\n'
        for trial in trials
    )
    # Without a Windows sandbox Codex rejects every shell command ("blocked by policy"). The
    # elevated sandbox must be set up per home through an administrator prompt, so use the
    # unelevated one, which needs none.
    sandbox = '\n[windows]\nsandbox = "unelevated"\n'
    (home / "config.toml").write_text(
        "[features]\nhooks = true\n" + sandbox + trust, encoding="utf-8"
    )


def prepare(
    base: Path,
    reps: int,
    arms: tuple[str, ...] = ARMS,
    baseline_from: Path | None = None,
    task_set: str = "standard",
) -> None:
    """`arms` limits the run to the setups being changed; `baseline_from` names an earlier run
    whose no-PRISM sessions are the comparison (they do not depend on PRISM's code)."""
    if base.exists():
        raise ValueError("choose a fresh benchmark directory")
    if base.is_relative_to(ROOT) or base.is_relative_to(AROGYA):
        raise ValueError("benchmark copies must be outside the source repositories")
    base.mkdir(parents=True)
    engine_sha = _copy_engine(base / "engine")
    entry = base / "engine_entry.py"
    entry.write_text(ENGINE_ENTRY.format(engine=str(base / "engine")), encoding="utf-8")
    (base / "agy_mcp.py").write_text(AGY_DISPATCH.format(entry=str(entry)), encoding="utf-8")
    template = base / "templates" / "arogya"
    template.mkdir(parents=True)
    files = git_archive(AROGYA, AROGYA_REV, template)
    (template / "AGENTS.md").write_text(COMMON, encoding="utf-8")
    sources = {"standard": [TASKS], "hard": [HARD_TASKS], "all": [TASKS, HARD_TASKS]}[task_set]
    tasks = [
        t
        for source in sources
        for t in json.loads(source.read_text(encoding="utf-8"))
        if t["repo"] == "arogya"
    ]
    (base / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(CHECKS, base / "checks.py")
    rng = random.Random(SEED)
    schedule: list[list[Any]] = []
    for rep in range(1, reps + 1):  # a complete first pass before any repetition
        cells = [[host, t["id"], arm, rep] for host in HOSTS for t in tasks for arm in arms]
        rng.shuffle(cells)
        schedule.extend(cells)
    (base / "schedule.json").write_text(json.dumps(schedule) + "\n", encoding="utf-8")
    _codex_home(base, [trial_dir(base, h, t, a, r) for h, t, a, r in schedule if h == "codex"])
    versions = {}
    for host, command in (("codex", "codex"), ("claude", "claude"), ("antigravity", "agy")):
        try:
            out = subprocess.run(
                [shutil.which(command) or command, "--version"],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()
        except OSError:
            out = "not installed"
        versions[host] = out.splitlines()[0] if out else "unknown"
    registration = {
        "engine": "working tree of PRISM at preparation",
        "engine_sha256": engine_sha,
        "engine_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "repository": {"source": str(AROGYA), "revision": AROGYA_REV, "files": len(files)},
        "tasks": len(tasks),
        "task_set": task_set,
        "arms": arms,
        "baseline_from": str(baseline_from) if baseline_from else None,
        "hosts": versions,
        "models": MODELS,
        "reps": reps,
        "sessions": len(schedule),
        "seed": SEED,
        "auth": "existing subscription sign-ins; API keys removed",
        "normalisation": {
            "fresh_input": "uncached input",
            "cost_equivalent": f"fresh + {CACHE_READ_WEIGHT} x cache_read + {CACHE_WRITE_WEIGHT} x 5-minute or {CACHE_WRITE_1H_WEIGHT} x 1-hour cache_write + output",
            "antigravity": "input_tokens excludes cache_read_tokens (reads often exceed it), so both count as input",
        },
    }
    (base / "registration.json").write_text(
        json.dumps(registration, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared {len(schedule)} sessions at {base}", flush=True)


# --- one trial -----------------------------------------------------------------------------------


def _git_commit(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "--all"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=PRISM benchmark", "-c", "user.email=benchmark@localhost",
         "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", message],
        cwd=repo, check=True, capture_output=True,
    )  # fmt: skip


def _command(base: Path) -> str:
    """The hook command prefix. Unquoted: PowerShell (Codex) treats a quoted first word as a
    string, not a program, so paths with spaces are refused instead of quoted."""
    python, entry = Path(sys.executable).as_posix(), (base / "engine_entry.py").as_posix()
    if any(character.isspace() for character in python + entry):
        raise ValueError("the Python and benchmark paths must not contain spaces")
    return f"{python} {entry}"


def _rewrite_hooks(path: Path, command: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"prism hook', '"' + command + " hook"), "utf-8")


def _mcp_entry(base: Path) -> dict[str, Any]:
    return {"command": sys.executable, "args": [str(base / "engine_entry.py"), "mcp"]}


def setup_trial(base: Path, host: str, task: dict[str, Any], arm: str, rep: int) -> dict[str, Any]:
    trial = trial_dir(base, host, task["id"], arm, rep)
    if trial.exists():
        _remove(trial)  # an interrupted earlier attempt; its result was never recorded
    repo, logs = trial / "repo", trial / "logs"
    logs.mkdir(parents=True)
    shutil.copytree(base / "templates" / "arogya", repo)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _git_commit(repo, "Frozen benchmark source")
    env = environment(trial / "config")
    env["PRISM_BENCH_TRIAL"] = str(trial)
    env["GIT_CEILING_DIRECTORIES"] = str(trial)
    if host == "codex":
        env["CODEX_HOME"] = str(base / "codex-home")
    started = time.monotonic()
    if arm != "baseline":
        hooks, mcp = arm in ("hook", "hook_mcp"), arm in ("mcp", "hook_mcp")
        code = (
            "import sys;from pathlib import Path;from prism.lifecycle import apply_init,plan_init,scan;"
            "from prism.integrations import IntegrationOptions;r=Path(sys.argv[1]);"
            "apply_init(plan_init(r,[sys.argv[2]],IntegrationOptions(hooks=sys.argv[3]=='1',mcp=sys.argv[4]=='1')));"
            "scan(r)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(repo), INTEGRATION[host], str(int(hooks)), str(int(mcp))],
            cwd=base, env={**env, "PYTHONPATH": str(base / "engine")},
            capture_output=True, timeout=300,
        )  # fmt: skip
        (logs / "setup.stdout").write_bytes(result.stdout)
        (logs / "setup.stderr").write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(f"PRISM setup failed for {trial}")
        command = _command(base)
        _rewrite_hooks(repo / ".codex/hooks.json", command)
        _rewrite_hooks(repo / ".claude/settings.json", command)
        _rewrite_hooks(repo / ".agents/hooks.json", command)
        config = repo / ".codex/config.toml"
        if config.is_file():
            text = config.read_text(encoding="utf-8")
            text = text.replace('command = "prism"', "command = " + json.dumps(sys.executable))
            text = text.replace(
                'args = ["mcp"]', "args = " + json.dumps([str(base / "engine_entry.py"), "mcp"])
            )
            config.write_text(text, encoding="utf-8")
        if host == "codex" and hooks and not config.is_file():
            config.write_text("[features]\nhooks = true\n", encoding="utf-8")
        if mcp:
            (trial / "mcp-enabled").write_text("1", encoding="utf-8")
        bin_dir = trial / "bin"
        bin_dir.mkdir()
        python, entry = Path(sys.executable).as_posix(), (base / "engine_entry.py").as_posix()
        (bin_dir / "prism.cmd").write_text(f'@echo off\r\n"{python}" "{entry}" %*\r\n', "utf-8")
        (bin_dir / "prism").write_text(f'#!/bin/sh\nexec "{python}" "{entry}" "$@"\n', "utf-8")
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        _git_commit(repo, "Prepared arm integration")
    mcp_config = {"mcpServers": {"prism": _mcp_entry(base)} if arm in ("mcp", "hook_mcp") else {}}
    (trial / "mcp.json").write_text(json.dumps(mcp_config), encoding="utf-8")
    return {
        "trial": trial,
        "repo": repo,
        "logs": logs,
        "env": env,
        "setup_seconds": time.monotonic() - started,
    }


def host_command(
    base: Path, host: str, arm: str, t: dict[str, Any]
) -> tuple[list[str], str | None]:
    """The native command line, and the prompt to send on stdin (None: it is in the arguments)."""
    prompt = COMMON + AUTHORIZED + ARM_NOTE.get(arm, "") + "\nRequest: " + t["task"]["prompt"]
    repo, logs = t["repo"], t["logs"]
    if host == "codex":
        args = [
            "codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
            "-c", 'approval_policy="never"', "-m", MODELS["codex"],
            "-c", 'forced_login_method="chatgpt"', "-c", 'model_reasoning_effort="medium"',
            "-c", "features.hooks=true", "-c", "sandbox_workspace_write.network_access=false",
            "--add-dir", str(logs), "--json", "-C", str(repo),
        ]  # fmt: skip
        if arm in ("hook", "hook_mcp"):
            args.append("--dangerously-bypass-hook-trust")  # only the frozen PRISM hook commands
        return [*args, "-"], prompt
    if host == "claude":
        return [
            "claude", "-p", "--output-format", "stream-json", "--verbose",
            "--model", MODELS["claude"], "--setting-sources", "project",
            "--strict-mcp-config", "--mcp-config", str(t["trial"] / "mcp.json"),
            "--no-session-persistence", "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash", "Read", "Edit", "MultiEdit", "Write", "Glob", "Grep",
            "mcp__prism__prism_task",
            "--disallowedTools", "WebFetch", "WebSearch",
        ], prompt  # fmt: skip
    return [
        "agy", "-p", prompt, "--output-format", "stream-json", "--model", MODELS["antigravity"],
        "--dangerously-skip-permissions", "--disable-slash-commands",
    ], None  # fmt: skip


# --- usage parsing (shared by the final row and the live counter) --------------------------------


def _events(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def normalised(
    fresh: int, read: int, write: int, output: int, write_1h: int = 0, **extra: Any
) -> dict[str, Any]:
    """`write_1h`: the part of `write` that went to the 1-hour cache (priced higher)."""
    write_1h = min(write_1h, write)
    weighted_write = CACHE_WRITE_WEIGHT * (write - write_1h) + CACHE_WRITE_1H_WEIGHT * write_1h
    return {
        "fresh_input": fresh,
        "cache_read": read,
        "cache_write": write,
        "cache_write_1h": write_1h,
        "input_total": fresh + read + write,
        "output": output,
        "total": fresh + read + write + output,
        "cost_equivalent": round(fresh + CACHE_READ_WEIGHT * read + weighted_write + output, 1),
        **extra,
    }


def codex_rollout(base: Path, events: list[dict[str, Any]]) -> Path | None:
    thread = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
    if not thread:
        return None
    found = list((base / "codex-home" / "sessions").rglob(f"*{thread}*.jsonl"))
    return found[0] if len(found) == 1 else None


def usage(base: Path, host: str, logs: Path) -> dict[str, Any] | None:
    """Normalised usage so far (live) or final, from the host's own records only."""
    events = _events(logs / "events.jsonl")
    if host == "codex":
        done = [e for e in events if e.get("type") == "turn.completed" and e.get("usage")]
        raw = done[-1]["usage"] if done else None
        if raw is None:  # live: the rollout's cumulative token counter
            rollout = codex_rollout(base, events)
            for event in reversed(_events(rollout) if rollout else []):
                info = (event.get("payload") or {}).get("info") or {}
                if event.get("payload", {}).get("type") == "token_count" and info.get(
                    "total_token_usage"
                ):
                    raw = info["total_token_usage"]
                    break
        if raw is None:
            return None
        cached = int(raw.get("cached_input_tokens", 0))
        return normalised(
            int(raw.get("input_tokens", 0)) - cached, cached, 0, int(raw.get("output_tokens", 0)),
            reasoning=int(raw.get("reasoning_output_tokens", 0)), final=bool(done),
        )  # fmt: skip
    if host == "claude":
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result and result.get("modelUsage"):
            models = result["modelUsage"].values()  # every model, subagents included
            write = sum(int(m.get("cacheCreationInputTokens", 0)) for m in models)
            # modelUsage has no cache-lifetime split; apply the main usage's split to it.
            split = (result.get("usage") or {}).get("cache_creation") or {}
            hour = int(split.get("ephemeral_1h_input_tokens", 0))
            known = hour + int(split.get("ephemeral_5m_input_tokens", 0))
            return normalised(
                sum(int(m.get("inputTokens", 0)) for m in models),
                sum(int(m.get("cacheReadInputTokens", 0)) for m in models),
                write,
                sum(int(m.get("outputTokens", 0)) for m in models),
                write_1h=round(write * hour / known) if known else 0,
                turns=result.get("num_turns"), final=True,
            )  # fmt: skip
        seen: dict[str, dict[str, Any]] = {}
        for event in events:
            message = event.get("message") or {}
            if event.get("type") == "assistant" and message.get("usage") and message.get("id"):
                seen[message["id"]] = message["usage"]  # streamed copies repeat one message's usage
        if not seen:
            return None
        return normalised(
            sum(int(u.get("input_tokens", 0)) for u in seen.values()),
            sum(int(u.get("cache_read_input_tokens", 0)) for u in seen.values()),
            sum(int(u.get("cache_creation_input_tokens", 0)) for u in seen.values()),
            sum(int(u.get("output_tokens", 0)) for u in seen.values()),
            write_1h=sum(
                int((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0))
                for u in seen.values()
            ),
            final=False,
        )  # fmt: skip
    result = next((e["result"] for e in reversed(events) if e.get("event") == "result"), None)
    if result is not None and result.get("status") == "ERROR":
        return None  # the host failed the session; its zero usage is not a measurement
    steps = [
        e["step_update"]["usage"]
        for e in events
        if e.get("event") == "step_update" and (e.get("step_update") or {}).get("usage")
    ]
    raw = (result or {}).get("usage")
    if raw is None and steps:
        raw = {
            key: sum(int(s.get(key, 0)) for s in steps)
            for key in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens")
        }
    if not raw:
        return None
    # agy's input_tokens excludes cache reads: a step's cache_read_tokens often exceeds its
    # input_tokens, and its total_tokens is input + output. Both are input; thinking is output.
    return normalised(
        int(raw.get("input_tokens", 0)), int(raw.get("cache_read_tokens", 0)), 0,
        int(raw.get("output_tokens", 0)) + int(raw.get("thinking_tokens", 0)),
        thinking=int(raw.get("thinking_tokens", 0)),
        turns=(result or {}).get("num_turns"), final=result is not None,
    )  # fmt: skip


_QUOTA = (
    "quota reached",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "usage limit",
    "429",
    "too many requests",
)


def quota_error(logs: Path) -> bool:
    """Did the host refuse the session for quota or rate limits? Such a session measures
    nothing: it is a failure to retry, never a 0-token result."""
    try:
        text = (logs / "stderr.txt").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        text = ""
    for event in _events(logs / "events.jsonl"):
        result = event.get("result") if event.get("event") == "result" else None
        if isinstance(result, dict) and result.get("status") == "ERROR":
            text += " " + str(result.get("error", "")).lower()
        if event.get("type") in ("error", "turn.failed"):
            text += " " + json.dumps(event).lower()
    return any(marker in text for marker in _QUOTA)


def answer_text(host: str, logs: Path) -> str:
    events = _events(logs / "events.jsonl")
    if host == "codex":
        return "\n".join(
            e["item"].get("text", "")
            for e in events
            if e.get("type") == "item.completed"
            and e.get("item", {}).get("type") == "agent_message"
        )
    if host == "claude":
        result = next((e for e in reversed(events) if e.get("type") == "result"), {})
        return str(result.get("result") or "")
    result = next((e["result"] for e in reversed(events) if e.get("event") == "result"), {})
    return str(result.get("response") or "")


def tool_calls(host: str, logs: Path) -> dict[str, int]:
    """How the agent navigated: PRISM CLI, PRISM MCP, other shell commands and file reads."""
    counts: dict[str, int] = defaultdict(int)
    for event in _events(logs / "events.jsonl"):
        text = json.dumps(event)
        if host == "codex" and event.get("type") == "item.completed":
            kind = event.get("item", {}).get("type")
            if kind == "mcp_tool_call":
                counts["prism_mcp"] += 1
            elif kind == "command_execution":
                counts[
                    "prism_cli" if "prism" in str(event["item"].get("command")) else "shell"
                ] += 1
        elif host == "claude" and event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    command = str((block.get("input") or {}).get("command", ""))
                    key = (
                        "prism_mcp" if name.startswith("mcp__prism")
                        else "prism_cli" if name == "Bash" and "prism " in command
                        else name.lower()
                    )  # fmt: skip
                    counts[key] += 1
        elif host == "antigravity" and event.get("event") == "step_update":
            step = event["step_update"]
            if step.get("step_type") == "tool" and step.get("state") == "DONE":
                name = str(step.get("tool_name", ""))
                key = (
                    "prism_mcp" if "prism_task" in name or (name == "call_mcp_tool" and "prism" in text)
                    else "prism_cli" if name == "run_command" and "prism " in text
                    else name
                )  # fmt: skip
                counts[key] += 1
    return dict(counts)


# --- running ------------------------------------------------------------------------------------


def run_trial(base: Path, host: str, task: dict[str, Any], arm: str, rep: int) -> dict[str, Any]:
    t = setup_trial(base, host, task, arm, rep)
    t["task"] = task
    repo, logs, env = t["repo"], t["logs"], t["env"]
    paths = sorted(source_inventory(repo))
    before = source_hashes(repo, paths)
    args, stdin = host_command(base, host, arm, t)
    # Windows launchers (`codex.cmd`) are only found through PATHEXT, which Popen does not use.
    args[0] = shutil.which(args[0], path=env.get("PATH")) or args[0]
    (logs / "command.json").write_text(json.dumps([*args[:3], "..."]), encoding="utf-8")
    started, timeout = time.monotonic(), False
    with (logs / "events.jsonl").open("wb") as out, (logs / "stderr.txt").open("wb") as err:
        process = subprocess.Popen(
            args, cwd=repo, env=env, stdout=out, stderr=err,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            shell=False,
        )  # fmt: skip
        try:
            process.communicate(
                stdin.encode("utf-8") if stdin is not None else None, timeout=SESSION_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            timeout = True
            process.kill()
            process.communicate()
    seconds = time.monotonic() - started
    answer = answer_text(host, logs)
    (logs / "answer.txt").write_text(answer, encoding="utf-8")
    after_paths = sorted(set(paths) | source_inventory(repo))
    after = source_hashes(repo, after_paths)
    changed = sorted(
        p for p in after
        if before.get(p) != after[p] and not p.startswith((".aicontext/", ".codex/", ".claude/", ".agents/"))
        and p not in ("AGENTS.md", "CLAUDE.md", ".mcp.json", "pyproject.toml")
    )  # fmt: skip
    if task.get("readonly"):
        success = not changed and all(
            value.lower() in answer.lower().replace("\\", "/") for value in task["required"]
        )
    else:
        check = subprocess.run(
            [sys.executable, "-I", str(base / "checks.py"), str(repo), task["checker"]],
            cwd=logs, env=environment(logs / "evaluator-config"), capture_output=True, timeout=120,
        )  # fmt: skip
        (logs / "check.stdout").write_bytes(check.stdout)
        (logs / "check.stderr").write_bytes(check.stderr)
        success = check.returncode == 0
    hooks = _events(logs / "hooks.jsonl")
    measured = usage(base, host, logs)
    limited = quota_error(logs)
    row = {
        "host": host,
        "model": MODELS[host],
        "task": task["id"],
        "kind": task["kind"],
        "arm": arm,
        "rep": rep,
        "success": bool(success and process.returncode == 0 and not timeout and not limited),
        "status": "quota"
        if limited
        else "timeout"
        if timeout
        else "completed"
        if process.returncode == 0
        else "host_failure",
        "exit_code": process.returncode,
        "seconds": round(seconds, 1),
        "setup_seconds": round(t["setup_seconds"], 1),
        "usage_known": bool(measured and measured.get("final")) and not limited,
        "usage": measured,
        "hook_fired": any(h["hook"] in ("user-prompt", "pre-invocation") for h in hooks),
        "hook_delivered": any(
            h["hook"] in ("user-prompt", "pre-invocation")
            and h.get("output", "").strip() not in ("", "{}")
            for h in hooks
        ),
        "tools": tool_calls(host, logs),
        "changed_files": changed,
        "raw": str(logs.relative_to(base)),
    }
    (logs / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    with _LOCK, (base / "results.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    # The evidence is the diff and the logs; a 90 MB repository copy per session fills a disk.
    patch = subprocess.run(
        ["git", "diff", "--no-ext-diff", "HEAD", "--", "."], cwd=repo, capture_output=True
    ).stdout
    (logs / "source.patch").write_bytes(patch)
    _remove(repo)
    return row


def _remove(path: Path) -> None:
    def writable(function: Any, target: str, _: Any) -> None:
        os.chmod(target, 0o700)  # Git's object files are read-only on Windows
        function(target)

    shutil.rmtree(path, onexc=writable)


def _agy_mcp(base: Path, add: bool) -> None:
    listed = subprocess.run(
        ["agy", "mcp", "list"], capture_output=True, text=True, timeout=60
    ).stdout
    ours = base / "agy-mcp-installed"
    if add:
        if "prism" in listed.split() or "prism:" in listed:
            raise RuntimeError(
                "an Antigravity MCP server named prism already exists; not replacing it"
            )
        subprocess.run(
            ["agy", "mcp", "add", "--env", "PRISM_MCP_PROFILE=lean", "prism", sys.executable,
             str(base / "agy_mcp.py")],
            check=True, capture_output=True, timeout=60,
        )  # fmt: skip
        ours.write_text("1", encoding="utf-8")
    elif ours.exists():
        subprocess.run(["agy", "mcp", "remove", "prism"], capture_output=True, timeout=60)
        ours.unlink()


def _sync_codex_auth(base: Path) -> None:
    """If a session refreshed the copied sign-in, give the refreshed one back so the real one
    (whose refresh token was just rotated away) keeps working."""
    copy = base / "codex-home" / "auth.json"
    real = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    try:
        mine, theirs = json.loads(copy.read_text("utf-8")), json.loads(real.read_text("utf-8"))
    except (OSError, ValueError):
        return
    if (mine.get("last_refresh") or "") > (theirs.get("last_refresh") or ""):
        mine.pop("OPENAI_API_KEY", None)
        real.write_text(
            json.dumps({**theirs, **mine, "OPENAI_API_KEY": theirs.get("OPENAI_API_KEY")}), "utf-8"
        )
        print(
            "Codex sign-in was refreshed during the run; the refreshed copy was restored.",
            flush=True,
        )


def run(base: Path, workers: int, only: str | None) -> None:
    tasks = {t["id"]: t for t in json.loads((base / "tasks.json").read_text(encoding="utf-8"))}
    schedule = json.loads((base / "schedule.json").read_text(encoding="utf-8"))
    # Sessions the host refused (quota) or never measured are run again.
    done = {
        (r["host"], r["task"], r["arm"], r["rep"])
        for r in _events(base / "results.jsonl")
        if r.get("usage_known") and r.get("status") != "quota"
    }
    queues: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for host, task, arm, rep in schedule:
        if (host, task, arm, rep) not in done and (only is None or host == only):
            queues[host].append((host, task, arm, rep))
    if "antigravity" in queues:
        _agy_mcp(base, add=True)
    failures: dict[str, int] = defaultdict(int)

    def worker(queue: list[tuple[str, str, str, int]]) -> None:
        while True:
            with _LOCK:
                if not queue:
                    return
                host, task, arm, rep = queue.pop(0)
            if failures[host] >= HOST_FAILURE_LIMIT:
                return  # a host failing repeatedly (quota, sign-in): stop it, keep the others
            while shutil.disk_usage(base).free < MIN_FREE_BYTES:
                time.sleep(30)  # wait for running sessions to finish and free their copies
            try:
                row = run_trial(base, host, tasks[task], arm, rep)
                if row["status"] == "quota":
                    failures[host] = HOST_FAILURE_LIMIT  # pause this host; rerun after the reset
                    print(
                        f"{host}: quota or rate limit reached; its remaining sessions wait",
                        flush=True,
                    )
                else:
                    failures[host] = 0 if row["usage_known"] else failures[host] + 1
            except Exception as exc:  # setup trouble in one cell must not stop the campaign
                failures[host] += 1
                cell = {"host": host, "task": task, "arm": arm, "rep": rep, "error": repr(exc)}
                try:
                    with _LOCK, (base / "errors.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps(cell) + "\n")
                except OSError:
                    print(json.dumps(cell), flush=True)  # a full disk must not kill the worker

    try:
        with ThreadPoolExecutor(max_workers=workers * max(1, len(queues))) as pool:
            for queue in queues.values():
                for _ in range(workers):
                    pool.submit(worker, queue)
    finally:
        if "antigravity" in queues:
            _agy_mcp(base, add=False)
        _sync_codex_auth(base)
    print("Run finished", flush=True)


# --- live counter and report ---------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summary(base: Path) -> dict[str, Any]:
    rows = [r for r in _events(base / "results.jsonl") if r.get("usage_known")]
    registration = base / "registration.json"
    earlier = (
        json.loads(registration.read_text(encoding="utf-8")).get("baseline_from")
        if registration.exists()
        else None
    )
    if earlier and not any(r["arm"] == "baseline" for r in rows):
        rows += [
            r
            for r in _events(Path(earlier) / "results.jsonl")
            if r.get("usage_known") and r["arm"] == "baseline"
        ]
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cells[(row["host"], row["arm"])].append(row)
    out: dict[str, Any] = {}
    for host in HOSTS:
        baseline = {(r["task"], r["rep"]): r for r in cells.get((host, "baseline"), [])}
        for arm in ARMS:
            group = cells.get((host, arm), [])
            if not group:
                continue
            paired = [
                (r, baseline[(r["task"], r["rep"])])
                for r in group
                if (r["task"], r["rep"]) in baseline and arm != "baseline"
            ]

            def change(key: str, paired: list[Any] = paired) -> float | None:
                pairs = [(a["usage"][key], b["usage"][key]) for a, b in paired if b["usage"][key]]
                if not pairs:
                    return None
                return 100 * (sum(a for a, _ in pairs) / sum(b for _, b in pairs) - 1)

            out[f"{host}/{arm}"] = {
                "host": host,
                "arm": arm,
                "sessions": len(group),
                "success_rate": sum(r["success"] for r in group) / len(group),
                "mean": {
                    key: _mean([r["usage"][key] for r in group])
                    for key in (
                        "fresh_input",
                        "cache_read",
                        "cache_write",
                        "input_total",
                        "output",
                        "total",
                        "cost_equivalent",
                    )
                },
                "mean_seconds": _mean([r["seconds"] for r in group]),
                "paired_with_baseline": len(paired),
                "change_vs_baseline_pct": {
                    key: change(key)
                    for key in ("input_total", "fresh_input", "output", "cost_equivalent")
                },
                "hook_delivered_rate": sum(r["hook_delivered"] for r in group) / len(group),
                "prism_calls": sum(
                    r["tools"].get("prism_cli", 0) + r["tools"].get("prism_mcp", 0) for r in group
                ),
            }
    return out


def _running(base: Path) -> list[dict[str, Any]]:
    finished = {r["raw"] for r in _events(base / "results.jsonl")}
    live = []
    for host in HOSTS:
        for trial in (base / "runs" / host).glob("*") if (base / "runs" / host).is_dir() else []:
            logs = trial / "logs"
            if not (logs / "events.jsonl").exists() or str(logs.relative_to(base)) in finished:
                continue
            if (logs / "result.json").exists():
                continue
            measured = usage(base, host, logs) or {}
            live.append(
                {
                    "host": host,
                    "trial": trial.name,
                    "input": measured.get("input_total", 0),
                    "output": measured.get("output", 0),
                    "cost_equivalent": measured.get("cost_equivalent", 0),
                    "age": time.time() - (logs / "events.jsonl").stat().st_ctime,
                }
            )
    return live


def watch(base: Path, interval: float) -> None:
    from rich.console import Group
    from rich.live import Live
    from rich.table import Table

    schedule = json.loads((base / "schedule.json").read_text(encoding="utf-8"))
    total_by_host: dict[str, int] = defaultdict(int)
    for host, *_ in schedule:
        total_by_host[host] += 1

    def fmt(value: float | None, pct: bool = False) -> str:
        if value is None:
            return "-"
        return f"{value:+.1f}%" if pct else f"{value:,.0f}"

    def render() -> Group:
        rows = _events(base / "results.jsonl")
        stats = summary(base)
        head = Table(title="PRISM benchmark: sessions", expand=True)
        for column in ("host", "done", "failed/unknown", "running", "tokens so far (input+output)"):
            head.add_column(column)
        live = _running(base)
        for host in HOSTS:
            mine = [r for r in rows if r["host"] == host]
            tokens = sum((r.get("usage") or {}).get("total", 0) for r in mine)
            tokens += sum(x["input"] + x["output"] for x in live if x["host"] == host)
            head.add_row(
                host, f"{len(mine)}/{total_by_host[host]}",
                str(sum(not r.get("usage_known") or r["status"] != "completed" for r in mine)),
                str(sum(x["host"] == host for x in live)), fmt(tokens),
            )  # fmt: skip
        table = Table(
            title="Normalised tokens per session (mean) and change vs the same host's baseline",
            expand=True,
        )
        for column in ("host", "arm", "n", "success", "input total", "fresh input", "output",
                       "cost-equiv", "Δ input", "Δ cost-equiv", "hook delivered", "PRISM calls", "sec"):  # fmt: skip
            table.add_column(column, justify="right" if column not in ("host", "arm") else "left")
        for s in stats.values():
            change = s["change_vs_baseline_pct"]
            table.add_row(
                s["host"], s["arm"], str(s["sessions"]), f"{s['success_rate']:.0%}",
                fmt(s["mean"]["input_total"]), fmt(s["mean"]["fresh_input"]), fmt(s["mean"]["output"]),
                fmt(s["mean"]["cost_equivalent"]), fmt(change["input_total"], True),
                fmt(change["cost_equivalent"], True), f"{s['hook_delivered_rate']:.0%}",
                str(s["prism_calls"]), fmt(s["mean_seconds"]),
            )  # fmt: skip
        running = Table(title="Live sessions", expand=True)
        for column in (
            "host",
            "session",
            "input so far",
            "output so far",
            "cost-equiv",
            "elapsed s",
        ):
            running.add_column(column)
        for x in sorted(live, key=lambda x: (x["host"], x["trial"])):
            running.add_row(
                x["host"], x["trial"], fmt(x["input"]), fmt(x["output"]),
                fmt(x["cost_equivalent"]), f"{x['age']:.0f}",
            )  # fmt: skip
        return Group(head, table, running)

    with Live(render(), refresh_per_second=1, screen=False) as display:
        while True:
            time.sleep(interval)
            display.update(render())


def rescore(base: Path) -> None:
    """Recompute every recorded session's usage from its raw logs (after a parser fix).

    The previous results file is kept beside the new one; nothing is re-run."""
    path = base / "results.jsonl"
    rows = _events(path)
    backup = base / f"results.before-rescore-{int(time.time())}.jsonl"
    shutil.copyfile(path, backup)
    for row in rows:
        logs = base / row["raw"]
        measured = usage(base, row["host"], logs)
        row["usage"] = measured
        row["usage_known"] = bool(measured and measured.get("final"))
        (logs / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(f"Rescored {len(rows)} sessions; previous results kept in {backup.name}", flush=True)


def report(base: Path) -> Path:
    registration = json.loads((base / "registration.json").read_text(encoding="utf-8"))
    stats = summary(base)
    all_rows = _events(base / "results.jsonl")
    lines = [
        "# PRISM multi-host benchmark", "",
        f"Repository: ArogyaTrack @ {registration['repository']['revision'][:10]} "
        f"({registration['repository']['files']} files), {registration['tasks']} tasks, "
        f"{registration['reps']} repetition(s).", "",
        "Hosts and models: " + ", ".join(
            f"{h} {registration['hosts'][h]} ({registration['models'][h]})" for h in HOSTS
        ) + ".", "",
        f"Sessions recorded: {len(all_rows)} of {registration['sessions']}; usage known for "
        f"{sum(bool(r.get('usage_known')) for r in all_rows)}.", "",
        "Cost-equivalent = fresh input + 0.1 x cache read + 1.25 x cache write + output. "
        "Changes are paired with the same host's baseline on the same task and repetition.", "",
        "| host | arm | n | success | input total | fresh input | output | cost-equiv | Δ input | Δ cost-equiv | hook delivered | PRISM calls | sec |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]  # fmt: skip

    def f(value: float | None, pct: bool = False) -> str:
        return "-" if value is None else (f"{value:+.1f}%" if pct else f"{value:,.0f}")

    for s in stats.values():
        c = s["change_vs_baseline_pct"]
        lines.append(
            f"| {s['host']} | {s['arm']} | {s['sessions']} | {s['success_rate']:.0%} | "
            f"{f(s['mean']['input_total'])} | {f(s['mean']['fresh_input'])} | {f(s['mean']['output'])} | "
            f"{f(s['mean']['cost_equivalent'])} | {f(c['input_total'], True)} | {f(c['cost_equivalent'], True)} | "
            f"{s['hook_delivered_rate']:.0%} | {s['prism_calls']} | {f(s['mean_seconds'])} |"
        )
    path = base / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (base / "summary.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "operation", choices=("prepare", "run", "watch", "report", "trial", "rescore")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--task-set", choices=("standard", "hard", "all"), default="standard")
    parser.add_argument(
        "--baseline-from", type=Path, help="reuse an earlier run's no-PRISM sessions"
    )
    parser.add_argument("--workers", type=int, default=4, help="parallel sessions per host")
    parser.add_argument("--only", choices=HOSTS)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--cell", nargs=4, metavar=("HOST", "TASK", "ARM", "REP"))
    args = parser.parse_args()
    base = args.output.resolve()
    if args.operation == "prepare":
        prepare(base, args.reps, tuple(args.arms), args.baseline_from, args.task_set)
    elif args.operation == "run":
        run(base, args.workers, args.only)
    elif args.operation == "watch":
        watch(base, args.interval)
    elif args.operation == "rescore":
        rescore(base)
    elif args.operation == "trial":  # one cell, for smoke tests
        host, task, arm, rep = args.cell
        tasks = {t["id"]: t for t in json.loads((base / "tasks.json").read_text(encoding="utf-8"))}
        if host == "antigravity":
            _agy_mcp(base, add=True)
        try:
            print(json.dumps(run_trial(base, host, tasks[task], arm, int(rep)), indent=2))
        finally:
            if host == "antigravity":
                _agy_mcp(base, add=False)
    else:
        text = report(base).read_text(encoding="utf-8")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(
                encoding="utf-8"
            )  # the table uses Δ; Windows consoles default to cp1252
        print(text)


if __name__ == "__main__":
    main()
