"""Bounded, disposable task packets keyed by source revision and presentation budget."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prism.config import load_config
from prism.core.paths import AICONTEXT
from prism.writers.json_writer import write_json

FORMAT = 5
MAX_PACKETS = 32


def source_stamp(root: Path, manifest: dict[str, Any]) -> str | None:
    """Cheap change guard, including sources not present in the delivered packet."""
    rows = []
    try:
        # External graph exports have their own revision/verification path; do
        # not mask a changed advisory relationship with a source-only cache key.
        if load_config(root).extra.get("graphify_graph") is not None:
            return None
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
    key = json.dumps((FORMAT, stamp, query, budget, mode))
    digest = hashlib.sha256(key.encode()).hexdigest()
    return root / AICONTEXT / "cache" / "tasks" / f"{digest}.json"


def load_packet(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") == FORMAT and isinstance(data.get("packet"), dict):
            return dict(data["packet"])
    except (OSError, ValueError, AttributeError):
        pass
    return None


def packet_current(root: Path, manifest: dict[str, Any], packet: dict[str, Any]) -> bool:
    """Never return cached code solely on a timestamp check: verify delivered files."""
    try:
        files = {block["file"] for block in packet["blocks"]}
        files.update(
            o["file"] for literal in packet.get("literals", []) for o in literal["occurrences"]
        )
        files.update(link["file"] for link in packet.get("links", []) if link.get("snippet"))
        for file in files:
            path = (root / file).resolve()
            if not path.is_relative_to(root.resolve()):
                return False
            expected = manifest["files"][file]["sha256"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
        return isinstance(packet.get("budget"), dict)
    except (OSError, KeyError, TypeError):
        return False


def save_packet(path: Path, packet: dict[str, Any]) -> None:
    try:
        write_json(path, {"format": FORMAT, "packet": packet})
        entries = sorted(
            path.parent.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True
        )
        for old in entries[MAX_PACKETS:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass  # a cache cannot make navigation fail
