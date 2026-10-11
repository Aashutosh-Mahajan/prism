"""Bound disposable shell logs without deleting indexes, notes or unknown files."""

from __future__ import annotations

import re
import time
from pathlib import Path

TEE_KEEP = 40
TEE_BYTES = 32 * 1024 * 1024
TEE_AGE_DAYS = 30
_LOG = re.compile(r"\d{6}-[0-9a-f]{8}\.(?:txt|meta\.json)")


def _safe_directory(directory: Path) -> bool:
    # A symlink at any level could redirect cleanup into an unrelated directory.
    return not any(path.is_symlink() for path in (directory, *directory.parents))


def cache_size(root: Path) -> tuple[int, int]:
    from prism.consent import cache_root

    directory = cache_root(root)
    if not _safe_directory(directory):
        return 0, 0
    count = size = 0
    pending = [directory]
    while pending:
        current = pending.pop()
        try:
            for path in current.iterdir():
                if path.is_symlink():
                    continue
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    size += path.stat().st_size
                    count += 1
        except OSError:
            continue
    return count, size


def collect_tee(
    root: Path,
    *,
    keep: int = TEE_KEEP,
    max_bytes: int = TEE_BYTES,
    age_days: float = TEE_AGE_DAYS,
    now: float | None = None,
) -> dict[str, int | bool]:
    """Keep newest complete log groups within all limits; unlink regular leaves only."""
    from prism.outputfilter import tee_dir

    if keep < 0 or max_bytes < 0 or age_days < 0:
        raise ValueError("cache limits must be non-negative")
    directory = tee_dir(root)
    result: dict[str, int | bool] = {
        "removed_files": 0,
        "removed_bytes": 0,
        "kept_logs": 0,
        "kept_bytes": 0,
        "skipped": 0,
        "unsafe_path": False,
    }
    if not _safe_directory(directory):
        result["unsafe_path"] = True
        return result
    groups: dict[str, list[tuple[Path, int, float]]] = {}
    try:
        for path in directory.iterdir():
            if not _LOG.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                result["skipped"] += 1
                continue
            stat = path.stat()
            identity = path.name.split(".", 1)[0]
            groups.setdefault(identity, []).append((path, stat.st_size, stat.st_mtime))
    except OSError:
        return result
    cutoff = (time.time() if now is None else now) - age_days * 86400
    ordered = sorted(groups.items(), key=lambda item: (-max(p[2] for p in item[1]), item[0]))
    for _, files in ordered:
        size = sum(p[1] for p in files)
        has_log = any(p[0].suffix == ".txt" for p in files)
        retain = (
            has_log
            and max(p[2] for p in files) >= cutoff
            and result["kept_logs"] < keep
            and result["kept_bytes"] + size <= max_bytes
        )
        if retain:
            result["kept_logs"] += 1
            result["kept_bytes"] += size
            continue
        for path, length, _ in files:
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                    result["skipped"] += 1
                    continue
                path.unlink()
                result["removed_files"] += 1
                result["removed_bytes"] += length
            except OSError:
                result["skipped"] += 1
    return result
