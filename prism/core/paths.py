"""Well-known locations inside a repo."""

from __future__ import annotations

from pathlib import Path

AICONTEXT = ".aicontext"
MANIFEST = "manifest.json"
GITIGNORE_LINES = (".aicontext/cache/", ".aicontext/audit/scratch/")


def aicontext_dir(root: Path) -> Path:
    return root / AICONTEXT


def manifest_path(root: Path) -> Path:
    return aicontext_dir(root) / MANIFEST


def find_repo_root(start: Path) -> Path:
    """Nearest index or Git boundary, else `start`; never cross a nested repository."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / AICONTEXT).is_dir() or (candidate / ".git").exists():
            return candidate
    return start
