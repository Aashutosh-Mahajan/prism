"""Google Antigravity (experimental): a workspace rule and the navigation skill.

Antigravity reads workspace rules from `.agent/rules/` and skills from `.agents/skills/`
(`.agent/skills/` is still read). Its MCP servers live in a user-level file, which PRISM never
edits on its own: `init` prints the entry to add. I could not find documented hooks, so
freshness relies on the query-time check every PRISM answer starts with.
"""

from __future__ import annotations

import json
from pathlib import Path

from prism.integrations.base import FileChange, Integration, IntegrationOptions, read_text
from prism.integrations.common import INSTRUCTION_BLOCK, MCP_ENTRY, skill_text

RULE = ".agent/rules/prism.md"
SKILL = ".agents/skills/prism-context/SKILL.md"
MANAGED = "<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->"
USER_MCP_FILE = "~/.gemini/antigravity/mcp_config.json"


def rule_text() -> str:
    return f"{MANAGED}\n\n{INSTRUCTION_BLOCK}"


class AntigravityIntegration(Integration):
    name = "antigravity"

    def detect(self, root: Path) -> bool:
        return (root / ".agent").is_dir() or (root / ".agents").is_dir()

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        changes = [
            FileChange(RULE, rule_text(), "workspace rule"),
            FileChange(SKILL, skill_text("prism-context"), "prism-context skill"),
        ]
        return [c for c in changes if not c.is_noop(root)]

    def plan_removal(self, root: Path) -> list[FileChange]:
        changes = [
            FileChange(path, None, detail)
            for path, detail in ((RULE, "PRISM rule"), (SKILL, "prism-context skill"))
            if (root / path).is_file()
        ]
        return [c for c in changes if not c.is_noop(root)]

    def notes(self, root: Path, options: IntegrationOptions) -> list[str]:
        if not options.mcp:
            return []
        entry = json.dumps({"mcpServers": {"prism": MCP_ENTRY}}, indent=2)
        return [
            f"Antigravity reads MCP servers from {USER_MCP_FILE} (user-level; PRISM does not edit "
            f"it). To give it the PRISM tools, add:\n{entry}"
        ]

    def status(self, root: Path) -> list[tuple[str, bool | None, str]]:
        rule = read_text(root / RULE)
        if rule is None:
            return []
        return [("antigravity rule", rule == rule_text(), ".agent/rules/prism.md installed")]
