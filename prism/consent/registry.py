"""Per-user, per-repo consent flags (CLAUDE.md Section 12.1).

Stored outside the repo in `~/.config/prism/repos.toml` (override the
directory with `PRISM_CONFIG_HOME`). Never committed, never shared.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from prism.writers.json_writer import write_text

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class RepoState(str, Enum):
    NOT_INITIALIZED = "not initialized"
    NOT_ENABLED = "initialized · not enabled for you"
    ENABLED = "enabled"
    PAUSED = "paused"


@dataclass(frozen=True)
class RepoEntry:
    repo_id: str
    enabled: bool
    paused: bool


def config_home() -> Path:
    override = os.environ.get("PRISM_CONFIG_HOME")
    return Path(override) if override else Path.home() / ".config" / "prism"


def registry_path() -> Path:
    return config_home() / "repos.toml"


def repo_key(root: Path) -> str:
    return root.resolve().as_posix()


def load_registry() -> dict[str, RepoEntry]:
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out: dict[str, RepoEntry] = {}
    for key, value in raw.get("repos", {}).items():
        if isinstance(value, dict):
            out[key] = RepoEntry(
                repo_id=str(value.get("repo_id", "")),
                enabled=bool(value.get("enabled", False)),
                paused=bool(value.get("paused", False)),
            )
    return out


def save_registry(entries: dict[str, RepoEntry]) -> None:
    lines = ["# PRISM per-user repo consent. Managed by `prism enable/disable/pause/resume`.", ""]
    for key in sorted(entries):
        e = entries[key]
        # JSON string literals are valid TOML basic strings.
        lines.append(f"[repos.{json.dumps(key)}]")
        lines.append(f"repo_id = {json.dumps(e.repo_id)}")
        lines.append(f"enabled = {'true' if e.enabled else 'false'}")
        lines.append(f"paused = {'true' if e.paused else 'false'}")
        lines.append("")
    write_text(registry_path(), "\n".join(lines))


def get_entry(root: Path) -> RepoEntry | None:
    return load_registry().get(repo_key(root))


def set_entry(root: Path, entry: RepoEntry | None) -> None:
    entries = load_registry()
    key = repo_key(root)
    if entry is None:
        entries.pop(key, None)
    else:
        entries[key] = entry
    save_registry(entries)


def repo_state(root: Path, repo_id: str | None) -> RepoState:
    """Consent state for this user. `repo_id` comes from the manifest (None if absent)."""
    if repo_id is None:
        return RepoState.NOT_INITIALIZED
    entry = get_entry(root)
    if entry is None or not entry.enabled or entry.repo_id != repo_id:
        return RepoState.NOT_ENABLED
    return RepoState.PAUSED if entry.paused else RepoState.ENABLED
