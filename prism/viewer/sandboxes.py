"""Prepare matching disposable sources. Folder copies are NOT an OS execution boundary."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from prism.consent.registry import config_home
from prism.core.errors import UserError
from prism.core.paths import AICONTEXT
from prism.integrations.base import without_block
from prism.lifecycle import scan
from prism.writers.json_writer import write_json
from prism.writers.manifest import new_manifest, write_manifest

_EXCLUDED = {
    ".git",
    ".aicontext",
    ".codex",
    ".claude",
    ".agents",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
}
MAX_SOURCE_BYTES = 200 * 1024 * 1024


def prepare_pair(root: Path, task: str) -> dict[str, Any]:
    """Pin HEAD, extract twice, index only With. No provider or agent is launched."""
    root = root.resolve()

    def git(*args: str) -> bytes:
        try:
            process = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UserError("Could not read the selected Git repository") from exc
        if process.returncode:
            raise UserError("Sandbox preparation requires a committed local Git repository")
        return process.stdout

    commit = git("rev-parse", "HEAD").decode().strip()
    tree = git("ls-tree", "-rz", commit)
    # An archive symlink/submodule is not a regular, self-contained source snapshot.
    for tree_entry in tree.split(b"\0"):
        if tree_entry and tree_entry.split(b" ", 1)[0] in (b"120000", b"160000"):
            raise UserError(
                "Symlinks and submodules require an adapter; this preparer does not copy them"
            )
    archive = git("archive", "--format=zip", commit)
    if len(archive) > MAX_SOURCE_BYTES:
        raise UserError("Source archive exceeds the 200 MB preparation limit")
    files: dict[str, bytes] = {}
    excluded: list[str] = []
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        if sum(entry.file_size for entry in source.infolist()) > MAX_SOURCE_BYTES:
            raise UserError("Expanded source exceeds the 200 MB preparation limit")
        for entry in source.infolist():
            if entry.is_dir():
                continue
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or ":" in entry.filename
            ):
                raise UserError("Unsafe archive path")
            if (
                any(part in _EXCLUDED for part in path.parts)
                or path.name == ".env"
                or (
                    path.name.startswith(".env.")
                    and path.name not in (".env.example", ".env.sample")
                )
                or path.name in ("auth.json", "credentials.json")
            ):
                excluded.append(path.as_posix())
                continue
            data = source.read(entry)
            if path.name in ("AGENTS.md", "CLAUDE.md"):
                try:
                    data = (without_block(data.decode("utf-8")) or "").encode("utf-8")
                except UnicodeDecodeError as exc:
                    raise UserError("Agent instruction files must be UTF-8") from exc
            files[path.as_posix()] = data
    ident = uuid.uuid4().hex
    parent = (config_home() / "dashboard-benchmarks").resolve()
    if parent.is_relative_to(root):
        raise UserError(
            "PRISM_CONFIG_HOME must be outside the original repository for sandbox preparation"
        )
    directory = parent / ident
    directory.mkdir(parents=True, exist_ok=False)
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    spec: dict[str, Any] = {
        "id": ident,
        "source_commit": commit,
        "task": task,
        "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
        "source_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "files": len(files),
        "excluded": excluded,
        "created": time.time(),
        "matching_source_verified": False,
        "baseline_prism_absent": False,
        "isolation_verified": False,
        "agent_sessions_started": 0,
        "state": "preparing",
        "original_dirty": bool(git("status", "--porcelain")),
        "limitations": [
            "Folder copies are prepared; OS execution isolation is not verified.",
            "Dependencies, host permissions, actual hook delivery and provider usage still require a managed adapter.",
            "Uncommitted source changes are excluded.",
        ],
        "arms": {arm: str(directory / arm) for arm in ("without", "with")},
    }
    write_json(directory / "preparation.json", spec)
    try:
        for arm in ("without", "with"):
            destination = directory / arm
            destination.mkdir()
            for relative, data in files.items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                if hashlib.sha256(target.read_bytes()).hexdigest() != hashes[relative]:
                    raise UserError("Source extraction did not match the frozen snapshot")
        spec["matching_source_verified"] = True
        baseline = directory / "without"
        spec["baseline_prism_absent"] = not (baseline / AICONTEXT).exists()
        indexed = directory / "with"
        write_manifest(indexed, new_manifest())
        started = time.monotonic()
        manifest = scan(indexed, warm=False)
        spec["indexing"] = {
            "seconds": time.monotonic() - started,
            "stats": manifest["stats"],
            "llm_calls": 0,
            "llm_tokens": 0,
            "cache_warmup": "not performed",
        }
        # Core indexing must not modify frozen source, even in the disposable copy.
        if any(
            hashlib.sha256((indexed / path).read_bytes()).hexdigest() != digest
            for path, digest in hashes.items()
        ):
            raise UserError("Indexing changed frozen source")
        spec["state"] = "source_copies_ready"
        write_json(directory / "preparation.json", spec)
        return spec
    except Exception:
        spec["state"] = "failed"
        write_json(directory / "preparation.json", spec)
        raise
