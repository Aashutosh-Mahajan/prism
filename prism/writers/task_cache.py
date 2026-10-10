"""Bounded, disposable task packets keyed by source revision and presentation budget."""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from prism.writers.json_writer import write_json

FORMAT = 7
MAX_PACKETS = 32


@lru_cache(maxsize=1)
def engine_fingerprint() -> str:
    """Identity of the retrieval code itself, so upgrading or editing Prism never serves an
    answer built by an older engine from the disposable packet cache."""
    package = Path(__file__).resolve().parents[1]
    rows = []
    for folder in ("navigator", "parsing", "core", "writers"):
        for file in sorted((package / folder).glob("*.py")):
            stat = file.stat()
            rows.append((folder, file.name, stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


# A long-lived process (the warm query process) re-checks the working tree itself right before it
# answers, so within this window the stat of every indexed file need not be repeated.
STAMP_TTL_SECONDS = 0.0
_STAMPS: dict[tuple[str, int], tuple[float, str | None]] = {}


def source_stamp(root: Path, manifest: dict[str, Any]) -> str | None:
    """Cheap change guard, including sources not present in the delivered packet."""
    if STAMP_TTL_SECONDS > 0:
        key = (root.as_posix(), id(manifest))
        hit = _STAMPS.get(key)
        if hit is not None and time.monotonic() - hit[0] < STAMP_TTL_SECONDS:
            return hit[1]
        value = _compute_stamp(root, manifest)
        _STAMPS.clear()
        _STAMPS[key] = (time.monotonic(), value)
        return value
    return _compute_stamp(root, manifest)


def _compute_stamp(root: Path, manifest: dict[str, Any]) -> str | None:
    rows = []
    try:
        for file, facts in sorted(manifest.get("files", {}).items()):
            stat = (root / file).stat()
            rows.append((file, facts.get("sha256"), stat.st_size, stat.st_mtime_ns))
        for name in ("prism.toml", "pyproject.toml"):
            path = root / name
            if path.is_file():
                stat = path.stat()
                rows.append((name, None, stat.st_size, stat.st_mtime_ns))
    except OSError:
        return None
    return hashlib.sha256(
        json.dumps((manifest.get("artifacts", {}), rows), sort_keys=True).encode()
    ).hexdigest()


def packet_path(root: Path, stamp: str, query: str, budget: int, mode: str) -> Path:
    key = json.dumps((FORMAT, engine_fingerprint(), stamp, query, budget, mode))
    digest = hashlib.sha256(key.encode()).hexdigest()
    from prism.consent import cache_root

    return cache_root(root) / "tasks" / f"{digest}.json"


def load_packet(path: Path) -> tuple[dict[str, Any], dict[str, str]] | None:
    """(packet, hashes of the text/data files it quotes), or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") == FORMAT and isinstance(data.get("packet"), dict):
            extra = data.get("text_sha256")
            return dict(data["packet"]), dict(extra) if isinstance(extra, dict) else {}
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _quoted_files(packet: dict[str, Any]) -> set[str]:
    files = {block["file"] for block in packet["blocks"]}
    files.update(
        o["file"] for literal in packet.get("literals", []) for o in literal["occurrences"]
    )
    files.update(link["file"] for link in packet.get("links", []) if link.get("snippet"))
    return files


def packet_current(
    root: Path,
    manifest: dict[str, Any],
    packet: dict[str, Any],
    text_sha256: dict[str, str] | None = None,
) -> bool:
    """Never return cached code solely on a timestamp check: verify the quoted files.

    Indexed files are checked against the manifest; text and data files (translations, config,
    docs), which the manifest does not list, against the hashes stored with the packet."""
    try:
        resolved = root.resolve()
        for file in _quoted_files(packet):
            path = (root / file).resolve()
            if not path.is_relative_to(resolved):
                return False
            known = manifest["files"].get(file)
            expected = known["sha256"] if known else (text_sha256 or {})[file]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
        return isinstance(packet.get("budget"), dict)
    except (OSError, KeyError, TypeError):
        return False


def save_packet(
    path: Path,
    packet: dict[str, Any],
    root: Path | None = None,
    manifest: dict[str, Any] | None = None,
) -> None:
    try:
        text_sha256: dict[str, str] = {}
        if root is not None and manifest is not None:
            for file in _quoted_files(packet):
                if file not in manifest.get("files", {}):
                    text_sha256[file] = hashlib.sha256((root / file).read_bytes()).hexdigest()
        write_json(path, {"format": FORMAT, "packet": packet, "text_sha256": text_sha256})
        entries = sorted(
            path.parent.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True
        )
        for old in entries[MAX_PACKETS:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass  # a cache cannot make navigation fail
