"""A detached, short-lived index update started by the post-edit hook.

`python -m prism.hooks.update_job <repo root> [changed files...]`. The hook returns to the agent
immediately; this process takes the update lock, brings the index up to date and exits.
A query that arrives meanwhile waits on the same lock, so it never sees a half-updated index.
"""

from __future__ import annotations

import contextlib
import sys
import traceback
from pathlib import Path

LOCK_WAIT_SECONDS = 20.0


def main(argv: list[str]) -> int:
    warm_only = bool(argv) and argv[0] == "--warm"
    argv = argv[1:] if warm_only else argv
    if not argv:
        return 0
    root = Path(argv[0])
    files = argv[1:] or None
    try:
        from prism.incremental.lock import LockBusy
        from prism.lifecycle import update
        from prism.navigator.freshness import warm_caches

        with contextlib.suppress(LockBusy):  # another updater is running and will pick it up
            if not warm_only:
                update(root, files=files, lock_wait=LOCK_WAIT_SECONDS)
            warm_caches(root)
    except BaseException:
        from prism.hooks.runner import _log

        _log(root, "background update failed:\n" + traceback.format_exc())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
