"""Answer from the current working tree, not from whenever the index was last updated.

Hooks keep the index fresh for agents that have them. Many agents do not, and an agent that
forgets to run `prism update` after an edit would otherwise get answers (or, worse, nothing)
for the files it just changed. Every navigator query therefore starts with a cheap check of
the working tree against the manifest and, if files changed, brings just those up to date.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism.consent import RepoState, repo_state
from prism.incremental.lock import LockBusy
from prism.status import working_tree_changes
from prism.writers.manifest import load_manifest

MAX_FILES = 300  # beyond this a rescan is a deliberate act, not a side effect of a query
LOCK_WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class RefreshState:
    state: str
    changed: int = 0
    updated: int = 0
    reason: str | None = None

    @property
    def complete(self) -> bool:
        return self.state in {"current", "updated"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "changed": self.changed,
            "updated": self.updated,
            "complete": self.complete,
            "reason": self.reason,
        }


_LAST_REFRESH: dict[str, tuple[float, RefreshState]] = {}


def last_refresh(root: Path) -> RefreshState | None:
    hit = _LAST_REFRESH.get(str(root.resolve()))
    return hit[1] if hit and time.monotonic() - hit[0] < 60 else None


def refresh_index(
    root: Path, max_files: int = MAX_FILES, wait: float = LOCK_WAIT_SECONDS
) -> RefreshState:
    """Explicit freshness result; skipped/failed maintenance is never a clean scope."""
    changed: list[str] = []
    try:
        manifest = load_manifest(root)
        if manifest is None or not manifest.get("last_scan"):
            state = RefreshState("missing", reason="index_missing")
        elif repo_state(root, manifest.get("repo_id")) is not RepoState.ENABLED:
            state = RefreshState("disabled", reason="consent")
        else:
            added, deleted, modified = working_tree_changes(root, manifest)
            changed = [*added, *deleted, *modified]
            if len(changed) > max_files:
                state = RefreshState("limited", len(changed), reason="change_limit")
            elif changed:
                from prism.lifecycle import update

                update(root, files=changed, lock_wait=wait)
                state = RefreshState("updated", len(changed), len(changed))
            else:
                state = RefreshState("current")
    except LockBusy:
        state = RefreshState("busy", len(changed), reason="update_locked")
    except Exception as exc:
        state = RefreshState("failed", len(changed), reason=type(exc).__name__)
    key = str(root.resolve())
    if len(_LAST_REFRESH) >= 128 and key not in _LAST_REFRESH:
        _LAST_REFRESH.pop(next(iter(_LAST_REFRESH)))
    _LAST_REFRESH[key] = (time.monotonic(), state)
    return state


COLD_FILES = 25  # more source files than this missing from the postings is a cold cache


def caches_ready(root: Path) -> bool:
    """True when a query would not have to build the symbol database or the source postings
    (a few changed files are fine; they are synchronised in milliseconds)."""
    from prism.navigator.cache_db import cache_dir, fingerprint
    from prism.navigator.source_index import pending_files

    manifest = load_manifest(root)
    if manifest is None or not manifest.get("last_scan"):
        return False
    if not (cache_dir(root) / f"index-{fingerprint(manifest)}.sqlite").is_file():
        return False
    if not (cache_dir(root) / "text-v1.sqlite").is_file():
        return False  # the text corpus is part of every packet query
    return pending_files(root, manifest) <= COLD_FILES


def warm_caches(root: Path) -> None:
    """Build the query caches (symbol database and source postings) now, so the first question
    after an index build does not pay for it. Best effort: a query builds them itself if not."""
    try:
        from prism.navigator.source_index import SourceIndex
        from prism.navigator.store import IndexStore

        store = IndexStore.open(root)
        try:
            index = SourceIndex(store)
            try:
                _ = index.text  # the text/data corpus is built lazily; slow on a large repo
            finally:
                index.close()
        finally:
            store.close()
    except Exception:
        return
    try:
        from prism.navigator.semantic import warm_vectors

        warm_vectors(root)  # only embeds when the user enabled semantic retrieval
    except Exception:
        return


def refresh_if_stale(
    root: Path, max_files: int = MAX_FILES, wait: float = LOCK_WAIT_SECONDS
) -> int:
    """Update the index for files changed since the last update. Returns how many changed.

    Does nothing unless PRISM is enabled for this user and not paused (the same consent that
    gates hooks), and never raises: a failed refresh leaves the previous index in place and
    answers still carry their own staleness warnings.
    """
    return refresh_index(root, max_files, wait).updated
