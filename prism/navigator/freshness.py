"""Answer from the current working tree, not from whenever the index was last updated.

Hooks keep the index fresh for agents that have them. Many agents do not, and an agent that
forgets to run `prism update` after an edit would otherwise get answers (or, worse, nothing)
for the files it just changed. Every navigator query therefore starts with a cheap check of
the working tree against the manifest and, if files changed, brings just those up to date.
"""

from __future__ import annotations

from pathlib import Path

from prism.consent import RepoState, repo_state
from prism.incremental.lock import LockBusy
from prism.status import working_tree_changes
from prism.writers.manifest import load_manifest

MAX_FILES = 300  # beyond this a rescan is a deliberate act, not a side effect of a query
LOCK_WAIT_SECONDS = 5.0


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
    return pending_files(root, manifest) <= COLD_FILES


def warm_caches(root: Path) -> None:
    """Build the query caches (symbol database and source postings) now, so the first question
    after an index build does not pay for it. Best effort: a query builds them itself if not."""
    try:
        from prism.navigator.source_index import SourceIndex
        from prism.navigator.store import IndexStore

        store = IndexStore.open(root)
        try:
            SourceIndex(store).close()
        finally:
            store.close()
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
    try:
        manifest = load_manifest(root)
        if manifest is None or not manifest.get("last_scan"):
            return 0
        if repo_state(root, manifest.get("repo_id")) is not RepoState.ENABLED:
            return 0
        added, deleted, modified = working_tree_changes(root, manifest)
        changed = [*added, *deleted, *modified]
        if not changed or len(changed) > max_files:
            return 0
        from prism.lifecycle import update

        update(root, files=changed, lock_wait=wait)
        return len(changed)
    except LockBusy:
        return 0
    except Exception:
        return 0
