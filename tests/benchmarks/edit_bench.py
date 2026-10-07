"""Live edit benchmark: the same change requests, one fresh agent session each, with and without
PRISM, scored by executable checks and measured from the agents' own transcripts.

    python -m tests.benchmarks.edit_bench prepare --repo <repo> --tasks <tasks.json> --out <dir>
    # run one fresh agent per prompt file in <dir>/prompts, each inside its own <dir>/<task>/<arm>
    python -m tests.benchmarks.edit_bench verify --out <dir>
    python -m tests.benchmarks.edit_bench measure --out <dir> --transcripts <dir-of-jsonl> --map map.json
    python -m tests.benchmarks.edit_bench report --out <dir>

Arms: `without` (the agent's normal tools), `tool` (PRISM is installed: the compact brief and the
instruction block are in context and `prism task` is available) and `hook` (as `tool`, plus what
the UserPromptSubmit hook would add to the request, produced by the real hook code).
Nothing here calls a model; it prepares sessions, checks results and does the arithmetic.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

ARMS = ("without", "tool", "hook")
IGNORE = shutil.ignore_patterns(
    ".git",
    ".claude",
    ".codex",
    ".kiro",
    ".aicontext",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".*_cache",
    ".env",
    ".env.*",
)
MISSING = object()


# --- preparing sessions -------------------------------------------------------------


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    ids = [t["id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise SystemExit("task ids must be unique")
    return list(tasks)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=bench@example.invalid", "-c", "user.name=bench", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _prompt(task: dict[str, Any], arm: str, repo: Path, brief: str, hook: str) -> str:
    parts = [
        "You are a coding agent taking part in a benchmark. Work ONLY inside this repository copy:",
        repo.as_posix(),
        "Make the requested change by editing files in that directory. Do not look outside it, do "
        "not use subagents, and do not run the app or its test suites. Be efficient: read only "
        "what you need.",
        "",
    ]
    if arm == "without":
        parts.append(
            "Use your normal tools (Glob, Grep, Read, Edit, and read-only shell commands). "
            "Do not use any tool called `prism`."
        )
    else:
        from prism.integrations.common import INSTRUCTION_BLOCK

        parts += [
            "SESSION CONTEXT (added by the PRISM session-start hook):",
            brief.strip(),
            "",
            "INSTRUCTIONS (from this repo's CLAUDE.md):",
            INSTRUCTION_BLOCK.strip(),
            f'Run prism from the repository directory, e.g.: cd "{repo.as_posix()}" && prism task "<request>"',
            "",
        ]
    parts += ["TASK:", task["request"].strip()]
    if arm == "hook" and hook:
        parts += [
            "",
            "ADDITIONAL CONTEXT (added by the PRISM UserPromptSubmit hook):",
            hook.strip(),
        ]
    parts += ["", "FINAL ANSWER: list each file you changed with one line each. Nothing else."]
    return "\n".join(parts) + "\n"


def hook_context(repo: Path, task: dict[str, Any], attempts: int = 4) -> str:
    """What the UserPromptSubmit hook adds to this task's request, from the real hook code.

    Files written moments ago are slow to open once (antivirus scans them), and a hook that runs
    out of time injects nothing, which would quietly turn the `hook` arm into the `tool` arm. So
    it asks again until the hook has answered."""
    from prism.hooks import user_prompt

    for _ in range(attempts):
        # A new session each time: an earlier attempt must not make this one skip code.
        payload = json.dumps(
            {"cwd": str(repo), "session_id": uuid.uuid4().hex, "prompt": task["request"]}
        )
        text = user_prompt(payload)
        if text:
            return text
    print(f"warning: the hook added nothing for {task['id']}")
    return ""


def refresh_hooks(out: Path) -> None:
    """Recompute every `hook` prompt after a change to PRISM, keeping the prepared copies."""
    previous = os.environ.get("PRISM_CONFIG_HOME")
    os.environ["PRISM_CONFIG_HOME"] = str(out / "cfg")
    try:
        from prism.navigator.api import op_brief

        for task in load_tasks(out / "tasks.json"):
            repo = out / task["id"] / "hook"
            text = _prompt(task, "hook", repo, op_brief(repo)["brief"], hook_context(repo, task))
            (out / "prompts" / f"{task['id']}-hook.txt").write_text(text, encoding="utf-8")
    finally:
        if previous is None:
            os.environ.pop("PRISM_CONFIG_HOME", None)
        else:
            os.environ["PRISM_CONFIG_HOME"] = previous


def prepare(source: Path, tasks_file: Path, out: Path, arms: tuple[str, ...] = ARMS) -> None:
    """Build one repository copy per task and arm, the PRISM arms indexed, and a prompt for each."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"refusing to overwrite a non-empty directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    cfg = out / "cfg"
    cfg.mkdir()
    previous = os.environ.get("PRISM_CONFIG_HOME")
    os.environ["PRISM_CONFIG_HOME"] = str(cfg)  # the real consent registry is never touched
    try:
        from prism.lifecycle import apply_init, plan_init, scan
        from prism.navigator.api import op_brief

        tasks = load_tasks(tasks_file)
        (out / "prompts").mkdir()
        (out / "tasks.json").write_text(json.dumps(tasks, indent=2), encoding="utf-8")
        # Named like the project, so the brief's title is what an agent really sees.
        base = out / "_base" / source.name
        shutil.copytree(source, base, ignore=IGNORE)
        indexed = out / "_indexed" / source.name
        shutil.copytree(base, indexed)
        apply_init(plan_init(indexed))
        scan(indexed)
        brief = op_brief(indexed)["brief"]
        for task in tasks:
            for arm in arms:
                repo = out / task["id"] / arm
                shutil.copytree(indexed if arm != "without" else base, repo)
                if arm != "without":
                    # A copy is a different path, so it needs its own (local) consent entry.
                    apply_init(plan_init(repo))
                hook = hook_context(repo, task) if arm == "hook" else ""
                _git(repo, "init", "-q")
                _git(repo, "add", "-A")
                _git(repo, "commit", "-qm", "baseline")
                text = _prompt(task, arm, repo, brief, hook)
                (out / "prompts" / f"{task['id']}-{arm}.txt").write_text(text, encoding="utf-8")
        shutil.rmtree(out / "_base", ignore_errors=True)
        shutil.rmtree(out / "_indexed", ignore_errors=True)
    finally:
        if previous is None:
            os.environ.pop("PRISM_CONFIG_HOME", None)
        else:
            os.environ["PRISM_CONFIG_HOME"] = previous


# --- scoring the result --------------------------------------------------------------


def _slice_python(source: str, name: str) -> str:
    """The function `name` plus every module-level function it (transitively) calls."""
    tree = ast.parse(source)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    needed: list[str] = []

    def collect(fn: str) -> None:
        if fn in needed or fn not in funcs:
            return
        needed.append(fn)
        for node in ast.walk(funcs[fn]):
            if isinstance(node, ast.Name):
                collect(node.id)

    collect(name)
    return "\n\n".join(ast.get_source_segment(source, funcs[n]) or "" for n in needed)


def _lookup(value: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return MISSING
    return value


def _run_python(check: dict[str, Any], repo: Path) -> list[tuple[str, bool]]:
    source = (repo / check["file"]).read_text(encoding="utf-8")
    scope: dict[str, Any] = {}
    exec(compile(_slice_python(source, check["function"]), check["file"], "exec"), scope)
    results = []
    for i, case in enumerate(check["cases"]):
        try:
            value = scope[check["function"]](*case.get("args", []), **case.get("kwargs", {}))
        except Exception as exc:
            results.append((f"{check['function']} case {i} runs ({type(exc).__name__})", False))
            continue
        for path, expected in case["expect"].items():
            got = _lookup(value, path)
            results.append((f"{check['function']}: {path} == {expected!r}", got == expected))
    return results


def _run_node(check: dict[str, Any], repo: Path) -> list[tuple[str, bool]]:
    text = (repo / check["file"]).read_text(encoding="utf-8")
    start = text.index(f"export const {check['function']}")
    end = text.index("\n};", start) + 3
    harness = (
        text[start:end]
        + f"\nconst cases: any[] = {json.dumps([c.get('args', []) for c in check['cases']])};\n"
    )
    harness += f"console.log(JSON.stringify(cases.map((a) => {check['function']}(...a))));\n"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "check.ts"
        script.write_text(harness, encoding="utf-8")
        run = subprocess.run(["node", str(script)], capture_output=True, text=True)
    try:
        values = json.loads(run.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [(f"{check['function']} runs in node", False)]
    results = []
    for case, value in zip(check["cases"], values, strict=True):
        for path, expected in case["expect"].items():
            results.append(
                (f"{check['function']}: {path} == {expected!r}", _lookup(value, path) == expected)
            )
    return results


def run_checks(task: dict[str, Any], repo: Path) -> dict[str, bool]:
    """Every check of a task against a repository copy (all must hold to pass)."""
    results: list[tuple[str, bool]] = []
    for check in task["checks"]:
        kind = check["type"]
        if kind in ("contains", "not_contains", "regex", "not_regex"):
            text = (repo / check["file"]).read_text(encoding="utf-8")
            needle = check["text"]
            if kind == "contains":
                ok = needle in text
            elif kind == "not_contains":
                ok = needle not in text
            elif kind == "regex":
                ok = re.search(needle, text) is not None
            else:
                ok = re.search(needle, text) is None
            results.append((f"{check['file']}: {kind} {needle!r}", ok))
        elif kind == "python_call":
            results += _run_python(check, repo)
        elif kind == "node_call":
            results += _run_node(check, repo)
        else:
            raise SystemExit(f"unknown check type {kind!r}")
    return dict(results)


def changed_files(repo: Path) -> list[str]:
    run = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", ".", ":(exclude).aicontext"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return [line for line in run.stdout.splitlines() if line.strip()]


def verify(out: Path) -> dict[str, dict[str, Any]]:
    tasks = {t["id"]: t for t in load_tasks(out / "tasks.json")}
    results: dict[str, dict[str, Any]] = {}
    for task_id, task in tasks.items():
        for arm in ARMS:
            repo = out / task_id / arm
            if not repo.is_dir():
                continue
            checks = run_checks(task, repo)
            results[f"{task_id}/{arm}"] = {
                "passed": sum(checks.values()),
                "total": len(checks),
                "failed": [name for name, ok in checks.items() if not ok],
                "changed": changed_files(repo),
            }
    (out / "verify.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


# --- measuring transcripts -----------------------------------------------------------


def measure_transcript(path: Path) -> dict[str, Any]:
    """Tokens, turns, tool calls and tool output from a Claude Code agent transcript (JSONL)."""
    sizes: list[int] = []
    seen: set[str] = set()
    fresh = written = cached = 0
    tools: dict[str, int] = {}
    tool_chars = 0
    stamps: list[float] = []
    prism_calls = 0
    from datetime import datetime

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("timestamp"):
            stamps.append(
                datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00")).timestamp()
            )
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        if rec.get("type") == "assistant":
            usage = msg.get("usage") or {}
            if usage and msg.get("id") not in seen:
                seen.add(str(msg.get("id")))
                parts = [
                    int(usage.get(k) or 0)
                    for k in (
                        "input_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                ]
                fresh, written, cached = fresh + parts[0], written + parts[1], cached + parts[2]
                sizes.append(sum(parts))
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name"))
                    tools[name] = tools.get(name, 0) + 1
                    command = (block.get("input") or {}).get("command", "")
                    if name == "Bash" and "prism " in str(command):
                        prism_calls += 1
        elif rec.get("type") == "user":
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        tool_chars += sum(
                            len(x.get("text", "")) for x in content if isinstance(x, dict)
                        )
                    elif isinstance(content, str):
                        tool_chars += len(content)
    return {
        "turns": len(sizes),
        "total_input": sum(sizes),
        "billable": round(fresh + written * 1.25 + cached * 0.1),
        "first_context": sizes[0] if sizes else 0,
        "last_context": sizes[-1] if sizes else 0,
        "work_context": sizes[-1] - sizes[0] if sizes else 0,
        "tool_calls": sum(tools.values()),
        "prism_calls": prism_calls,
        "tools": tools,
        "tool_output": tool_chars // 4,
        "seconds": round(stamps[-1] - stamps[0], 1) if len(stamps) > 1 else 0.0,
    }


def measure(out: Path, transcripts: Path, mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    """`mapping` names each session (`<task>/<arm>`) by its transcript file (without `.jsonl`)."""
    measured = {
        key: measure_transcript(transcripts / f"{name}.jsonl") for key, name in mapping.items()
    }
    (out / "measure.json").write_text(json.dumps(measured, indent=2), encoding="utf-8")
    return measured


# --- reporting -----------------------------------------------------------------------

_COLUMNS = (
    "turns",
    "total_input",
    "billable",
    "work_context",
    "tool_output",
    "tool_calls",
    "seconds",
)


def report(out: Path) -> str:
    measured = json.loads((out / "measure.json").read_text(encoding="utf-8"))
    verified = json.loads((out / "verify.json").read_text(encoding="utf-8"))
    arms = [a for a in ARMS if any(k.endswith(f"/{a}") for k in measured)]
    lines = ["| Metric | " + " | ".join(arms) + " |", "|---|" + "---:|" * len(arms)]
    means: dict[str, dict[str, float]] = {}
    for arm in arms:
        rows = [v for k, v in measured.items() if k.endswith(f"/{arm}")]
        means[arm] = {c: statistics.fmean(r[c] for r in rows) for c in _COLUMNS}
    base = means.get("without")
    for column in _COLUMNS:
        cells = []
        for arm in arms:
            value = means[arm][column]
            delta = (
                f" ({(value / base[column] - 1) * 100:+.0f}%)"
                if base and arm != "without" and base[column]
                else ""
            )
            cells.append(f"{value:,.0f}{delta}")
        lines.append(f"| {column} | " + " | ".join(cells) + " |")
    passed = []
    for arm in arms:
        rows = [v for k, v in verified.items() if k.endswith(f"/{arm}")]
        passed.append(f"{sum(r['passed'] for r in rows)}/{sum(r['total'] for r in rows)}")
    lines.append("| checks passed | " + " | ".join(passed) + " |")
    text = "\n".join(lines) + "\n"
    (out / "report.md").write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--tasks", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--arms", default=",".join(ARMS))
    for name in ("verify", "report", "refresh-hooks"):
        sub.add_parser(name).add_argument("--out", type=Path, required=True)
    m = sub.add_parser("measure")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--transcripts", type=Path, required=True)
    m.add_argument(
        "--map", type=Path, required=True, help="JSON {'<task>/<arm>': '<transcript name>'}"
    )
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.repo, args.tasks, args.out, tuple(args.arms.split(",")))
    elif args.command == "refresh-hooks":
        refresh_hooks(args.out)
    elif args.command == "verify":
        for key, row in verify(args.out).items():
            print(f"{key}: {row['passed']}/{row['total']}", row["failed"] or "")
    elif args.command == "measure":
        measure(args.out, args.transcripts, json.loads(args.map.read_text(encoding="utf-8")))
    else:
        print(report(args.out))


if __name__ == "__main__":
    main()
