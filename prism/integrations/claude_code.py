"""Claude Code: skills, hooks in `.claude/settings.json`, `.mcp.json`, CLAUDE.md block.

Hook format (Claude Code settings): `hooks.<Event>` is a list of
`{"matcher": str, "hooks": [{"type": "command", "command": str, "timeout": secs}]}`.
PRISM's entries are recognised by their `prism hook` command.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from prism.integrations.base import (
    FileChange,
    Integration,
    IntegrationOptions,
    dump_json,
    load_json,
    read_text,
    with_block,
    without_block,
)
from prism.integrations.common import INSTRUCTION_BLOCK, MCP_ENTRY, SKILL_NAMES, skill_text

SETTINGS = ".claude/settings.json"
MCP_JSON = ".mcp.json"
CLAUDE_MD = "CLAUDE.md"

HOOKS: dict[str, dict[str, Any]] = {
    "SessionStart": {
        "matcher": "startup|resume|clear|compact",
        "hooks": [{"type": "command", "command": "prism hook session-start", "timeout": 10}],
    },
    "PostToolUse": {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{"type": "command", "command": "prism hook post-edit", "timeout": 5}],
    },
}


def _is_prism_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(h, dict) and str(h.get("command", "")).startswith("prism hook")
        for h in entry.get("hooks", [])
    )


def strip_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(settings)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        entries = (
            [e for e in hooks[event] if not _is_prism_entry(e)]
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


def add_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    data = strip_hooks(settings)
    hooks = data.setdefault("hooks", {})
    for event, entry in HOOKS.items():
        hooks.setdefault(event, []).append(copy.deepcopy(entry))
    return data


def _json_change(root: Path, rel: str, data: dict[str, Any], detail: str) -> FileChange:
    return FileChange(rel, dump_json(data) if data else None, detail)


class ClaudeCodeIntegration(Integration):
    name = "claude-code"

    def detect(self, root: Path) -> bool:
        return (root / ".claude").is_dir() or (root / CLAUDE_MD).is_file()

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        changes = [
            FileChange(f".claude/skills/{name}/SKILL.md", skill_text(name), f"{name} skill")
            for name in SKILL_NAMES
        ]
        settings = load_json(root / SETTINGS)
        new_settings = add_hooks(settings) if options.hooks else strip_hooks(settings)
        if new_settings != settings or options.hooks:
            changes.append(
                _json_change(
                    root,
                    SETTINGS,
                    new_settings,
                    "SessionStart + PostToolUse(Edit|Write|MultiEdit) hooks",
                )
            )
        mcp = load_json(root / MCP_JSON)
        if options.mcp:
            new_mcp = copy.deepcopy(mcp)
            new_mcp.setdefault("mcpServers", {})["prism"] = MCP_ENTRY
            changes.append(_json_change(root, MCP_JSON, new_mcp, "MCP server `prism mcp` (stdio)"))
        changes.append(
            FileChange(
                CLAUDE_MD,
                with_block(read_text(root / CLAUDE_MD), INSTRUCTION_BLOCK),
                "short PRISM instruction block",
            )
        )
        return [c for c in changes if not c.is_noop(root)]

    def plan_removal(self, root: Path) -> list[FileChange]:
        changes = [
            FileChange(f".claude/skills/{name}/SKILL.md", None, f"{name} skill")
            for name in SKILL_NAMES
            if (root / f".claude/skills/{name}/SKILL.md").is_file()
        ]
        if (root / SETTINGS).is_file():
            changes.append(
                _json_change(root, SETTINGS, strip_hooks(load_json(root / SETTINGS)), "PRISM hooks")
            )
        if (root / MCP_JSON).is_file():
            mcp = copy.deepcopy(load_json(root / MCP_JSON))
            servers = mcp.get("mcpServers", {})
            if isinstance(servers, dict):
                servers.pop("prism", None)
                if not servers:
                    mcp.pop("mcpServers", None)
            changes.append(_json_change(root, MCP_JSON, mcp, "PRISM MCP server"))
        if (root / CLAUDE_MD).is_file():
            changes.append(
                FileChange(CLAUDE_MD, without_block(read_text(root / CLAUDE_MD)), "PRISM block")
            )
        return [c for c in changes if not c.is_noop(root)]
