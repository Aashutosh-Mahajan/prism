"""Merging PRISM's hook entries into an agent's hook configuration, and taking them out again.

Claude Code (`.claude/settings.json`), Codex (`.codex/hooks.json`) and Gemini CLI
(`.gemini/settings.json`) all keep `hooks.<Event>` as a list of
`{"matcher": str, "hooks": [{"type": "command", "command": str, ...}]}`; Cursor
(`.cursor/hooks.json`) keeps flat `{"command": str}` entries. PRISM's entries are recognised by
their `prism hook` command, so a user's own hooks are never touched.
"""

from __future__ import annotations

import copy
from typing import Any

PRISM_COMMAND_PREFIX = "prism hook"


def is_prism_entry(entry: Any) -> bool:
    """Nested form (`{"hooks": [{"command": ...}]}`) or Cursor's flat form (`{"command": ...}`)."""
    if not isinstance(entry, dict):
        return False
    if str(entry.get("command", "")).startswith(PRISM_COMMAND_PREFIX):
        return True
    return any(
        isinstance(h, dict) and str(h.get("command", "")).startswith(PRISM_COMMAND_PREFIX)
        for h in entry.get("hooks", [])
    )


def strip_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    """`settings` without any PRISM hook entry (empty events and an empty `hooks` are removed)."""
    data = copy.deepcopy(settings)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        entries = (
            [e for e in hooks[event] if not is_prism_entry(e)]
            if isinstance(hooks[event], list)
            else hooks[event]
        )
        if entries:
            hooks[event] = entries
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    return data


def add_hooks(settings: dict[str, Any], entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """`settings` with exactly PRISM's `entries` (one per event) after the user's own."""
    data = strip_hooks(settings)
    hooks = data.setdefault("hooks", {})
    for event, entry in entries.items():
        hooks.setdefault(event, []).append(copy.deepcopy(entry))
    return data
