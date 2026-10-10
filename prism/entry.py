"""The `prism` console entry point.

Host-agent hooks run on every edit and every session start, so `prism hook ...` is dispatched
before the full command line (typer, rich, every sub-command) is imported. Everything else
goes to `prism.cli`.
"""

from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "hook":
        from prism.hooks.entry import HOOKS, run_hook

        if argv[1] in HOOKS:
            run_hook(argv[1], argv[2:])
            return
    if argv[:1] == ["task"]:
        from prism.taskfast import try_fast

        if try_fast(argv[1:]):
            return
    from prism.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
