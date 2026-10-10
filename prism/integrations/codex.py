"""Codex: an AGENTS.md block, an MCP server in `.codex/config.toml`, hooks in `.codex/hooks.json`.

Codex reads project-level `.codex/` configuration only for a trusted project, and asks the user
to review new hooks (`/hooks`), so installing here never runs anything by itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from prism.integrations.base import (
    FileChange,
    Integration,
    IntegrationOptions,
    dump_json,
    load_json,
    outside_toml_block,
    read_text,
    with_block,
    with_toml_block,
    without_block,
    without_toml_block,
)
from prism.integrations.common import instruction_block
from prism.integrations.hooks_json import add_hooks, strip_hooks

AGENTS_MD = "AGENTS.md"
CONFIG_TOML = ".codex/config.toml"
HOOKS_JSON = ".codex/hooks.json"

MCP_TOML = """\
[mcp_servers.prism]
command = "prism"
args = ["mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 60
"""

HOOKS: dict[str, dict[str, Any]] = {
    "SessionStart": {
        "matcher": "startup|resume|clear",
        "hooks": [{"type": "command", "command": "prism hook session-start", "timeout": 10}],
    },
    "UserPromptSubmit": {
        "hooks": [{"type": "command", "command": "prism hook user-prompt", "timeout": 20}],
    },
    "PostToolUse": {
        "matcher": "apply_patch|Edit|Write",
        "hooks": [{"type": "command", "command": "prism hook post-edit", "timeout": 5}],
    },
    # Verified against Codex 0.162: a {"decision": "block", "reason": ...} answer sends the agent
    # back to work once (see prism/hooks/gate.py).
    "Stop": {
        "hooks": [{"type": "command", "command": "prism hook stop", "timeout": 20}],
    },
}

_USER_TABLE = re.compile(r"^\s*\[\s*mcp_servers\s*\.\s*prism\s*\]", re.MULTILINE)


class CodexIntegration(Integration):
    name = "codex"

    def detect(self, root: Path) -> bool:
        # Many tools read AGENTS.md, so it does not mean Codex is in use; a .codex/ folder does.
        return (root / ".codex").is_dir()

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        changes = [
            FileChange(
                AGENTS_MD,
                with_block(read_text(root / AGENTS_MD), instruction_block(options.mcp)),
                "PRISM instruction block",
            )
        ]
        config = read_text(root / CONFIG_TOML)
        # A table the user already wrote must not be declared twice: TOML would reject the file.
        user_defined = bool(_USER_TABLE.search(outside_toml_block(config)))
        if options.mcp and not user_defined:
            changes.append(
                FileChange(
                    CONFIG_TOML, with_toml_block(config, MCP_TOML), "MCP server `prism mcp` (stdio)"
                )
            )
        if options.hooks:
            hooks = load_json(root / HOOKS_JSON)
            changes.append(
                FileChange(
                    HOOKS_JSON,
                    dump_json(add_hooks(hooks, HOOKS)),
                    "hooks: SessionStart, UserPromptSubmit, PostToolUse(apply_patch), Stop",
                )
            )
        return [c for c in changes if not c.is_noop(root)]

    def plan_removal(self, root: Path) -> list[FileChange]:
        changes: list[FileChange] = []
        if (root / AGENTS_MD).is_file():
            changes.append(
                FileChange(AGENTS_MD, without_block(read_text(root / AGENTS_MD)), "PRISM block")
            )
        if (root / CONFIG_TOML).is_file():
            changes.append(
                FileChange(
                    CONFIG_TOML,
                    without_toml_block(read_text(root / CONFIG_TOML)),
                    "PRISM MCP server",
                )
            )
        if (root / HOOKS_JSON).is_file():
            remaining = strip_hooks(load_json(root / HOOKS_JSON))
            changes.append(
                FileChange(HOOKS_JSON, dump_json(remaining) if remaining else None, "PRISM hooks")
            )
        return [c for c in changes if not c.is_noop(root)]

    def notes(self, root: Path, options: IntegrationOptions) -> list[str]:
        if not (options.mcp or options.hooks):
            return []
        return [
            "Codex loads project-level .codex/ settings only for a trusted project. Trust this "
            "project, and review the new hooks with /hooks, before they take effect."
        ]

    def status(self, root: Path) -> list[tuple[str, bool | None, str]]:
        out: list[tuple[str, bool | None, str]] = []
        config = read_text(root / CONFIG_TOML)
        if config is not None:
            out.append(
                (
                    "codex mcp",
                    "mcp_servers.prism" in config,
                    ".codex/config.toml registers `prism mcp`",
                )
            )
        hooks = read_text(root / HOOKS_JSON)
        if hooks is not None:
            installed = [
                h
                for h in ("session-start", "user-prompt", "post-edit")
                if f"prism hook {h}" in hooks
            ]
            out.append(
                (
                    "codex hooks",
                    True if len(installed) == 3 else None,
                    ", ".join(installed) + " installed"
                    if installed
                    else "not installed (optional)",
                )
            )
        return out
