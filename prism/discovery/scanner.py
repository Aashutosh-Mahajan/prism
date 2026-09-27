"""Discovery: walk the repo and select source files.

Applies built-in ignores, every `.gitignore` in the tree (scoped to its
directory), `.prismignore`, config `ignore` patterns, a size limit, and a
binary check. Output is sorted by path for determinism.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pathspec

from prism.config import PrismConfig
from prism.core.models import SourceFile
from prism.discovery.language import detect_language

BUILTIN_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".aicontext",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "build",
        "dist",
        ".eggs",
        "site-packages",
        ".idea",
        ".vscode",
        "target",
        ".next",
        ".nuxt",
        "coverage",
        "htmlcov",
        ".gradle",
        "vendor",
    }
)
BINARY_SNIFF_BYTES = 8192


@dataclass
class _ScopedSpec:
    base: str  # repo-relative directory the ignore file lives in ("" for root)
    spec: pathspec.PathSpec

    def check(self, rel: str, is_dir: bool) -> bool | None:
        """True = ignored, False = re-included by a `!` pattern, None = no opinion."""
        if self.base:
            if not rel.startswith(self.base + "/"):
                return None
            rel = rel[len(self.base) + 1 :]
        result: bool | None = self.spec.check_file(rel + "/" if is_dir else rel).include
        return result


def _load_spec(path: Path) -> pathspec.PathSpec | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return pathspec.GitIgnoreSpec.from_lines(lines)


def _is_venv(dirpath: Path) -> bool:
    return (dirpath / "pyvenv.cfg").is_file()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_line(head: bytes) -> str:
    return head.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def discover(
    root: Path,
    config: PrismConfig,
    known: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[SourceFile]:
    """Select source files. `known` (manifest `files`) lets unchanged files skip hashing."""
    root = root.resolve()
    known = known or {}
    # .gitignore files, root first then deeper ones: the last file with an opinion wins,
    # matching git's precedence (a nested `!pattern` can re-include a file).
    specs: list[_ScopedSpec] = []
    prism_lines = [*config.ignore]
    prismignore = root / ".prismignore"
    if prismignore.is_file():
        prism_lines.extend(prismignore.read_text(encoding="utf-8", errors="replace").splitlines())
    prism_spec = _ScopedSpec("", pathspec.GitIgnoreSpec.from_lines(prism_lines))

    found: list[SourceFile] = []
    for dirpath_str, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath_str)
        rel_dir = dirpath.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir

        gitignore = dirpath / ".gitignore"
        if gitignore.is_file():
            spec = _load_spec(gitignore)
            if spec is not None:
                specs.append(_ScopedSpec(rel_dir, spec))

        def ignored(rel: str, is_dir: bool) -> bool:
            if prism_spec.check(rel, is_dir):
                return True
            decision: bool | None = None
            for spec in specs:
                verdict = spec.check(rel, is_dir)
                if verdict is not None:
                    decision = verdict
            return bool(decision)

        kept_dirs = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if d in BUILTIN_IGNORED_DIRS or d.endswith(".egg-info"):
                continue
            if _is_venv(dirpath / d) or ignored(rel, True):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs  # prune the walk in place

        for name in sorted(filenames):
            rel = f"{rel_dir}/{name}" if rel_dir else name
            full = dirpath / name
            if ignored(rel, False):
                continue
            try:
                stat = full.stat()
            except OSError:
                continue
            if stat.st_size > config.max_file_size:
                continue
            prev = known.get(rel)
            if (
                prev
                and prev.get("mtime") == stat.st_mtime
                and prev.get("size") == stat.st_size
                and prev.get("sha256")
                and prev.get("language")
            ):
                # Unchanged since the last run: skip the binary sniff and the hash.
                found.append(
                    SourceFile(
                        rel, str(prev["language"]), stat.st_size, str(prev["sha256"]), stat.st_mtime
                    )
                )
                continue
            language = detect_language(rel)
            head = b""
            if language is None or stat.st_size:
                try:
                    with full.open("rb") as fh:
                        head = fh.read(BINARY_SNIFF_BYTES)
                except OSError:
                    continue
            if b"\x00" in head:
                continue
            if language is None:
                language = detect_language(rel, _first_line(head))
                if language is None:
                    continue
            found.append(
                SourceFile(
                    path=rel,
                    language=language,
                    size=stat.st_size,
                    sha256=hash_file(full),
                    mtime=stat.st_mtime,
                )
            )
    found.sort(key=lambda f: f.path)
    return found
