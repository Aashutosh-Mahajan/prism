"""Cursor, Codex (and other AGENTS.md readers), and a generic fallback."""

from __future__ import annotations

import copy
from pathlib import Path

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
from prism.integrations.common import INSTRUCTION_BLOCK, MCP_ENTRY, skill_body

CURSOR_RULE = ".cursor/rules/prism.mdc"
CURSOR_MCP = ".cursor/mcp.json"
AGENTS_MD = "AGENTS.md"


def cursor_rule() -> str:
    """Navigation rules plus the refresh and audit procedures, as one always-on rule."""
    return (
        "---\n"
        "description: PRISM code index - navigation, brief refresh, and audit procedures\n"
        "alwaysApply: true\n"
        "---\n"
        "<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->\n\n"
        f"{INSTRUCTION_BLOCK}\n"
        "---\n\n"
        f"{skill_body('prism-context')}\n---\n\n"
        f"{skill_body('prism-refresh')}\n---\n\n"
        f"{skill_body('prism-audit')}"
    )


class CursorIntegration(Integration):
    name = "cursor"

    def detect(self, root: Path) -> bool:
        return (root / ".cursor").is_dir() or (root / ".cursorrules").is_file()

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        changes = [FileChange(CURSOR_RULE, cursor_rule(), "always-on PRISM rule")]
        if options.mcp:
            mcp = copy.deepcopy(load_json(root / CURSOR_MCP))
            mcp.setdefault("mcpServers", {})["prism"] = MCP_ENTRY
            changes.append(FileChange(CURSOR_MCP, dump_json(mcp), "MCP server `prism mcp` (stdio)"))
        return [c for c in changes if not c.is_noop(root)]

    def plan_removal(self, root: Path) -> list[FileChange]:
        changes = []
        if (root / CURSOR_RULE).is_file():
            changes.append(FileChange(CURSOR_RULE, None, "PRISM rule"))
        if (root / CURSOR_MCP).is_file():
            mcp = copy.deepcopy(load_json(root / CURSOR_MCP))
            servers = mcp.get("mcpServers", {})
            if isinstance(servers, dict):
                servers.pop("prism", None)
                if not servers:
                    mcp.pop("mcpServers", None)
            changes.append(
                FileChange(CURSOR_MCP, dump_json(mcp) if mcp else None, "PRISM MCP server")
            )
        return [c for c in changes if not c.is_noop(root)]


class AgentsMdIntegration(Integration):
    """Codex and other agents that read a root AGENTS.md. Also the generic fallback."""

    def __init__(self, name: str) -> None:
        self.name = name

    def detect(self, root: Path) -> bool:
        return self.name == "codex" and ((root / AGENTS_MD).is_file() or (root / ".codex").is_dir())

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        change = FileChange(
            AGENTS_MD,
            with_block(read_text(root / AGENTS_MD), INSTRUCTION_BLOCK),
            "PRISM instruction block",
        )
        return [] if change.is_noop(root) else [change]

    def plan_removal(self, root: Path) -> list[FileChange]:
        if not (root / AGENTS_MD).is_file():
            return []
        change = FileChange(AGENTS_MD, without_block(read_text(root / AGENTS_MD)), "PRISM block")
        return [] if change.is_noop(root) else [change]
