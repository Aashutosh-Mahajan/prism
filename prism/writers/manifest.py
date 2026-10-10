"""`manifest.json`: versions, per-file hashes, artifact hashes, scan timestamps.

This is the only `.aicontext/` file allowed to contain timestamps.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prism import SCHEMA_VERSION, __version__
from prism.core.models import SourceFile
from prism.core.paths import manifest_path
from prism.writers.json_writer import read_json, write_json

READ_ATTEMPTS = 20
READ_PAUSE = 0.025


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_manifest(root: Path) -> dict[str, Any] | None:
    path = manifest_path(root)
    if not path.is_file():
        return None
    data = None
    for attempt in range(READ_ATTEMPTS):
        try:
            data = read_json(path)
            break
        except PermissionError:
            # Windows refuses a read while the writer is replacing the file.
            if attempt == READ_ATTEMPTS - 1:
                raise
            time.sleep(READ_PAUSE)
    return data if isinstance(data, dict) else None


def new_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "prism_version": __version__,
        "repo_id": uuid.uuid4().hex,
        "created": now_iso(),
        "last_scan": None,
        "files": {},
        "artifacts": {},
        "stats": {},
        "drift": {"sections": {}},
    }


def write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    write_json(manifest_path(root), manifest)


def file_entries(files: list[SourceFile], parse_errors: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in files:
        entry: dict[str, Any] = {
            "sha256": f.sha256,
            "mtime": f.mtime,
            "size": f.size,
            "language": f.language,
        }
        if f.path in parse_errors:
            entry["parse_error"] = parse_errors[f.path]
        out[f.path] = entry
    return out


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
