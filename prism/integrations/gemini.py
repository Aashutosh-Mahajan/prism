"""Gemini CLI: a GEMINI.md block, plus an MCP server and hooks in `.gemini/settings.json`.

Gemini CLI reads `GEMINI.md` by default, lists MCP servers under `mcpServers` and hooks under
`hooks` (timeouts in milliseconds). `BeforeAgent` and `SessionStart` hooks add context through
`hookSpecificOutput.additionalContext`, so those two use `--format json`.
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
from prism.integrations.common import INSTRUCTION_BLOCK
from prism.integrations.hooks_json import add_hooks, strip_hooks

SETTINGS = ".gemini/settings.json"
GEMINI_MD = "GEMINI.md"
MCP_ENTRY: dict[str, Any] = {"command": "prism", "args": ["mcp"], "timeout": 60000}

HOOKS: dict[str, dict[str, Any]] = {
    "SessionStart": {
        "matcher": "startup|resume|clear",
        "hooks": [
            {
                "type": "command",
                "name": "prism-brief",
                "command": "prism hook session-start --format json --event SessionStart",
                "timeout": 10000,
            }
        ],
    },
    "BeforeAgent": {
        "matcher": ".*",
        "hooks": [
            {
                "type": "command",
                "name": "prism-context",
                "command": "prism hook user-prompt --format json --event BeforeAgent",
                "timeout": 10000,
            }
        ],
    },
    "AfterTool": {
        "matcher": "write_file|replace",
        "hooks": [
            {
                "type": "command",
                "name": "prism-update",
                "command": "prism hook post-edit",
                "timeout": 5000,
            }
        ],
    },
}


class GeminiIntegration(Integration):
    name = "gemini"

    def detect(self, root: Path) -> bool:
        return (root / ".gemini").is_dir() or (root / GEMINI_MD).is_file()

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        changes = [
            FileChange(
                GEMINI_MD,
                with_block(read_text(root / GEMINI_MD), INSTRUCTION_BLOCK),
                "PRISM instruction block",
            )
        ]
        settings = load_json(root / SETTINGS)
        new = copy.deepcopy(settings)
        if options.mcp:
            new.setdefault("mcpServers", {})["prism"] = MCP_ENTRY
        new = add_hooks(new, HOOKS) if options.hooks else strip_hooks(new)
        if new != settings:
            changes.append(
                FileChange(
                    SETTINGS,
                    dump_json(new),
                    "MCP server and hooks (SessionStart, BeforeAgent, AfterTool)",
                )
            )
        return [c for c in changes if not c.is_noop(root)]

    def plan_removal(self, root: Path) -> list[FileChange]:
        changes: list[FileChange] = []
        if (root / GEMINI_MD).is_file():
            changes.append(
                FileChange(GEMINI_MD, without_block(read_text(root / GEMINI_MD)), "PRISM block")
            )
        if (root / SETTINGS).is_file():
            settings = strip_hooks(load_json(root / SETTINGS))
            servers = settings.get("mcpServers")
            if isinstance(servers, dict):
                servers.pop("prism", None)
                if not servers:
                    settings.pop("mcpServers", None)
            changes.append(
                FileChange(
                    SETTINGS,
                    dump_json(settings) if settings else None,
                    "PRISM MCP server and hooks",
                )
            )
        return [c for c in changes if not c.is_noop(root)]

    def status(self, root: Path) -> list[tuple[str, bool | None, str]]:
        text = read_text(root / SETTINGS)
        if text is None:
            return []
        out: list[tuple[str, bool | None, str]] = [
            ("gemini mcp", '"prism"' in text, ".gemini/settings.json registers `prism mcp`")
        ]
        installed = [
            h for h in ("session-start", "user-prompt", "post-edit") if f"prism hook {h}" in text
        ]
        out.append(
            (
                "gemini hooks",
                True if len(installed) == 3 else None,
                ", ".join(installed) + " installed" if installed else "not installed (optional)",
            )
        )
        return out
