"""Shared machinery for agent integrations: planned file changes, managed blocks,
JSON merging, backups, and a ledger so uninstall can restore files exactly.

Integrations only install files and config. They never touch source code.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prism.core.paths import AICONTEXT
from prism.writers.json_writer import write_text

MARKER = "prism-managed"
BLOCK_START = "<!-- prism-managed:start -->"
BLOCK_END = "<!-- prism-managed:end -->"
_BLOCK_RE = re.compile(
    r"\n?" + re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.DOTALL
)


@dataclass(frozen=True)
class FileChange:
    path: str  # repo-relative (or absolute for user-level files)
    content: str | None  # None = delete
    detail: str

    def kind(self, root: Path) -> str:
        exists = self.resolve(root).exists()
        if self.content is None:
            return "delete"
        return "modify" if exists else "create"

    def resolve(self, root: Path) -> Path:
        p = Path(self.path)
        return p if p.is_absolute() else root / p

    def is_noop(self, root: Path) -> bool:
        target = self.resolve(root)
        if self.content is None:
            return not target.exists()
        try:
            return target.read_text(encoding="utf-8") == self.content
        except OSError:
            return False


@dataclass(frozen=True)
class IntegrationOptions:
    hooks: bool = True
    mcp: bool = True


class Integration(ABC):
    name: str

    @abstractmethod
    def detect(self, root: Path) -> bool:
        """True if the repo looks like it's used with this agent."""

    @abstractmethod
    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        """Changes that install (or refresh) this integration."""

    @abstractmethod
    def plan_removal(self, root: Path) -> list[FileChange]:
        """Changes that remove every PRISM-managed piece of this integration."""


# --- text helpers ----------------------------------------------------------------


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def with_block(existing: str | None, body: str) -> str:
    """Insert or replace the managed block, leaving everything else untouched."""
    block = f"{BLOCK_START}\n{body.strip()}\n{BLOCK_END}\n"
    if existing is None or not existing.strip():
        return block
    if BLOCK_START in existing:
        return _BLOCK_RE.sub("\n" + block, existing, count=1).lstrip("\n")
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + sep + block


def without_block(existing: str | None) -> str | None:
    """Remove the managed block. Returns None if nothing else is left (file can go)."""
    if existing is None or BLOCK_START not in existing:
        return existing
    remaining = _BLOCK_RE.sub("\n", existing).strip("\n")
    return (remaining + "\n") if remaining.strip() else None


def load_json(path: Path) -> dict[str, Any]:
    text = read_text(path)
    if not text or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        from prism.core.errors import UserError

        raise UserError(
            f"{path.name} is not valid JSON; fix it before PRISM edits it ({exc})"
        ) from exc
    return data if isinstance(data, dict) else {}


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# --- applying changes with backups and a ledger ----------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ledger_path(root: Path) -> Path:
    return root / AICONTEXT / "cache" / "integration.json"


def _load_ledger(root: Path) -> dict[str, Any]:
    text = read_text(ledger_path(root))
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def apply_changes(root: Path, changes: list[FileChange]) -> list[FileChange]:
    """Apply changes, backing up any file that already existed. Returns those applied."""
    ledger = _load_ledger(root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = root / AICONTEXT / "cache" / "backups" / stamp
    applied: list[FileChange] = []
    for change in changes:
        if change.is_noop(root):
            continue
        target = change.resolve(root)
        key = change.path
        entry = ledger.get(key)
        if target.exists() and entry is None:
            rel = Path(change.path.replace(":", "")).as_posix().lstrip("/")
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            entry = {"backup": backup.relative_to(root).as_posix(), "created": False}
        elif entry is None:
            entry = {"backup": None, "created": True}
        if change.content is None:
            target.unlink(missing_ok=True)
            ledger.pop(key, None)
        else:
            write_text(target, change.content)
            entry["sha_after"] = _sha(change.content)
            ledger[key] = entry
        applied.append(change)
    if ledger or ledger_path(root).exists():
        write_text(ledger_path(root), dump_json(dict(sorted(ledger.items()))))
    return applied


def remove_changes(root: Path, removals: list[FileChange]) -> list[FileChange]:
    """Uninstall: restore the original file if PRISM's copy is untouched, else surgically edit."""
    ledger = _load_ledger(root)
    applied: list[FileChange] = []
    for change in removals:
        target = change.resolve(root)
        entry = ledger.pop(change.path, None)
        current = read_text(target)
        if entry and current is not None and _sha(current) == entry.get("sha_after"):
            if entry.get("created"):
                target.unlink(missing_ok=True)
            elif entry.get("backup") and (root / entry["backup"]).is_file():
                shutil.copy2(root / entry["backup"], target)
            applied.append(change)
            continue
        if change.is_noop(root):
            continue
        if change.content is None:
            target.unlink(missing_ok=True)
        else:
            write_text(target, change.content)
        applied.append(change)
    if ledger_path(root).exists():
        write_text(ledger_path(root), dump_json(dict(sorted(ledger.items()))))
    return applied
