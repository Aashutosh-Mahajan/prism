"""A cross-process lock around index writes.

A hook, a query's freshness check and an explicit `prism update` can all want to update the
index at once. Artifacts are written atomically, but two writers deriving the index from
different disk states could still leave an older one last, so writers take turns.

The lock is a file created exclusively. A crashed holder is detected by age (never by
signalling its pid: on Windows `os.kill(pid, 0)` would terminate the process).
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from types import TracebackType

from prism.core.paths import AICONTEXT

STALE_AFTER_SECONDS = 300.0
POLL_SECONDS = 0.02


class LockBusy(RuntimeError):
    """Another process holds the update lock and did not release it within the wait."""


class UpdateLock:
    def __init__(self, root: Path, wait: float = 10.0) -> None:
        self.path = root / AICONTEXT / "cache" / "update.lock"
        self.wait = wait
        self._held = False

    def __enter__(self) -> UpdateLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._expired():
                    with contextlib.suppress(OSError):
                        self.path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    raise LockBusy(f"another update is running ({self.path.name})") from None
                time.sleep(POLL_SECONDS)
                continue
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {time.time():.0f}\n")
            self._held = True
            return self

    def _expired(self) -> bool:
        try:
            return time.time() - self.path.stat().st_mtime > STALE_AFTER_SECONDS
        except OSError:
            return False  # vanished: the next create attempt will succeed

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._held:
            with contextlib.suppress(OSError):
                self.path.unlink()
            self._held = False
