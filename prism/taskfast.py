"""Common task/find queries without importing the full command line.

Python start-up plus typer and rich cost about half a second before any work. When a warm
process is running, ask it directly. Otherwise use the same local query functions.
Unusual flags and errors fall back to the normal command line's validation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _parse(argv: list[str]) -> tuple[Path | None, dict[str, Any]] | None:
    query: str | None = None
    options: dict[str, Any] = {
        "budget": None,
        "mode": "auto",
        "session": None,
        "json": False,
        "detail": "full",
    }
    root: Path | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--budget", "--mode", "--session", "--root", "--detail") and i + 1 < len(argv):
            value = argv[i + 1]
            if arg == "--budget":
                if not value.isdigit() or not 128 <= int(value) <= 32000:
                    return None
                options["budget"] = int(value)
            elif arg == "--root":
                root = Path(value)
            else:
                options[arg[2:]] = value
            i += 2
        elif arg == "--json":
            options["json"] = True
            i += 1
        elif arg.startswith("-") or query is not None:
            return None  # anything unusual: let the full command line handle it
        else:
            query = arg
            i += 1
    if not query or not query.strip():
        return None
    return root, {"op": "task", "query": query, **options}


def try_fast(argv: list[str]) -> bool:
    try:
        parsed = _parse(argv)
        if parsed is None:
            return False
        root, request = parsed
        if root is not None and not root.is_dir():
            return False
        from prism.core.paths import find_repo_root
        from prism.navigator import daemon

        repo = (root or find_repo_root(Path.cwd())).resolve()
        text = daemon.ask(repo, request)
        if text is None:
            from prism.navigator.taskrun import open_fresh_store, run_task

            store = open_fresh_store(repo)
            try:
                text = run_task(
                    repo,
                    store,
                    request["query"],
                    request["budget"],
                    request["mode"],
                    request["session"],
                    request["json"],
                    request["detail"],
                )
            finally:
                store.close()
            daemon.ensure_running(repo)
        from prism.hooks.entry import use_utf8

        use_utf8()
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        return True
    except Exception:
        return False


def _parse_find(argv: list[str]) -> tuple[Path | None, dict[str, Any]] | None:
    request: dict[str, Any] = {
        "op": "find",
        "patterns": [],
        "regex": False,
        "ignore_case": False,
        "globs": [],
        "budget": 1500,
        "json": False,
    }
    root = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in {"--root", "--glob", "--budget"} and i + 1 < len(argv):
            value = argv[i + 1]
            if arg == "--root":
                root = Path(value)
            elif arg == "--glob":
                request["globs"].append(value)
            elif not value.isdigit() or not 128 <= int(value) <= 32000:
                return None
            else:
                request["budget"] = int(value)
            i += 2
        elif arg in {"--regex", "--json", "-i", "--ignore-case"}:
            request[
                {
                    "--regex": "regex",
                    "--json": "json",
                    "-i": "ignore_case",
                    "--ignore-case": "ignore_case",
                }[arg]
            ] = True
            i += 1
        elif arg.startswith("-"):
            return None
        else:
            request["patterns"].append(arg)
            i += 1
    return (root, request) if request["patterns"] else None


def try_find(argv: list[str]) -> bool:
    try:
        parsed = _parse_find(argv)
        if parsed is None:
            return False
        root, request = parsed
        if root is not None and not root.is_dir():
            return False
        from prism.core.paths import find_repo_root
        from prism.navigator import daemon

        repo = (root or find_repo_root(Path.cwd())).resolve()
        text = daemon.ask(repo, request)
        if text is None:
            import json

            from prism.navigator.find import render_find, run_find
            from prism.navigator.taskrun import open_fresh_store

            store = open_fresh_store(repo)
            try:
                result = run_find(
                    store,
                    request["patterns"],
                    request["regex"],
                    request["ignore_case"],
                    request["globs"],
                    request["budget"],
                )
            finally:
                store.close()
            text = (
                json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
                if request["json"]
                else render_find(result)
            )
        from prism.hooks.entry import use_utf8

        use_utf8()
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        return True
    except Exception:
        return False
