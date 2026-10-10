"""`prism task` answered by the warm query process without loading the full command line.

Python start-up plus typer and rich cost about half a second before any work. When a warm
process is running for this repo, this path asks it directly and prints the answer; in every
other case (no process, an unusual flag, any error) it returns False and the normal command runs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _parse(argv: list[str]) -> tuple[Path | None, dict[str, Any]] | None:
    query: str | None = None
    options: dict[str, Any] = {
        "budget": 2000,
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
            return False
        from prism.hooks.entry import use_utf8

        use_utf8()
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        return True
    except Exception:
        return False
