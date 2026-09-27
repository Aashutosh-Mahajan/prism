"""`prism install --global` / `prism uninstall --global`.

Adds (or removes) a short managed note in the user-level agent instruction
files. Never run implicitly. It enables nothing in any repo.
"""

from __future__ import annotations

from pathlib import Path

from prism.integrations.base import read_text, with_block, without_block
from prism.integrations.common import GLOBAL_NOTE, GLOBAL_SUGGEST
from prism.writers.json_writer import write_text


def global_files() -> list[Path]:
    home = Path.home()
    files = [home / ".claude" / "CLAUDE.md"]
    if (home / ".codex").is_dir():
        files.append(home / ".codex" / "AGENTS.md")
    return files


def install_global(suggest: bool = False) -> list[Path]:
    body = GLOBAL_NOTE + (GLOBAL_SUGGEST if suggest else "")
    changed = []
    for path in global_files():
        new = with_block(read_text(path), body)
        if read_text(path) != new:
            write_text(path, new)
            changed.append(path)
    return changed


def uninstall_global() -> list[Path]:
    changed = []
    for path in global_files():
        current = read_text(path)
        if current is None:
            continue
        new = without_block(current)
        if new == current:
            continue
        if new is None:
            path.unlink()
        else:
            write_text(path, new)
        changed.append(path)
    return changed
