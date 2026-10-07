"""Cursor, and the generic fallback for any agent that reads a root AGENTS.md."""

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
from prism.integrations.common import (
    INSTRUCTION_BLOCK,
    MCP_ENTRY,
    skill_body,
    skill_description,
)
from prism.integrations.hooks_json import add_hooks, strip_hooks

CURSOR_RULE = ".cursor/rules/prism.mdc"
CURSOR_MCP = ".cursor/mcp.json"
CURSOR_HOOKS = ".cursor/hooks.json"
AGENTS_MD = "AGENTS.md"
MANAGED = "<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->"
# Procedures an agent needs only now and then are rules it asks for by description, so they cost
# nothing in a session that never audits, refreshes or records a decision.
CURSOR_PROCEDURES = ("prism-audit", "prism-refresh", "prism-decisions")

CURSOR_HOOKS_ENTRIES: dict[str, dict[str, Any]] = {
    "sessionStart": {"command": "prism hook session-start --format cursor"},
    "afterFileEdit": {"command": "prism hook post-edit"},
}


def cursor_rule() -> str:
    """The always-on rule: only how to start a task. Short, because it is sent on every turn."""
    return (
        "---\n"
        "description: PRISM code index - start each task with `prism task`\n"
        "alwaysApply: true\n"
        "---\n"
        f"{MANAGED}\n\n"
        f"{INSTRUCTION_BLOCK}"
    )


def cursor_procedure(name: str) -> str:
    return (
        "---\n"
        f"description: {skill_description(name)}\n"
        "alwaysApply: false\n"
        "---\n"
        f"{MANAGED}\n\n"
        f"{skill_body(name)}"
    )


def _procedure_path(name: str) -> str:
    return f".cursor/rules/{name}.mdc"


class CursorIntegration(Integration):
    name = "cursor"

    def detect(self, root: Path) -> bool:
        return (root / ".cursor").is_dir() or (root / ".cursorrules").is_file()

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        changes = [FileChange(CURSOR_RULE, cursor_rule(), "always-on PRISM rule")]
        changes += [
            FileChange(_procedure_path(n), cursor_procedure(n), f"{n} rule (on request)")
            for n in CURSOR_PROCEDURES
        ]
        if options.mcp:
            mcp = copy.deepcopy(load_json(root / CURSOR_MCP))
            mcp.setdefault("mcpServers", {})["prism"] = MCP_ENTRY
            changes.append(FileChange(CURSOR_MCP, dump_json(mcp), "MCP server `prism mcp` (stdio)"))
        hooks = load_json(root / CURSOR_HOOKS)
        if options.hooks:
            merged = add_hooks(hooks, CURSOR_HOOKS_ENTRIES)
            # A fixed key order, so installing twice writes the same bytes.
            new = {"version": merged.get("version", 1)}
            new.update({k: v for k, v in merged.items() if k != "version"})
            changes.append(
                FileChange(CURSOR_HOOKS, dump_json(new), "hooks: sessionStart, afterFileEdit")
            )
        elif hooks:
            changes.append(FileChange(CURSOR_HOOKS, dump_json(strip_hooks(hooks)), "PRISM hooks"))
        return [c for c in changes if not c.is_noop(root)]

    def plan_removal(self, root: Path) -> list[FileChange]:
        changes = [
            FileChange(path, None, "PRISM rule")
            for path in (CURSOR_RULE, *(_procedure_path(n) for n in CURSOR_PROCEDURES))
            if (root / path).is_file()
        ]
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
        if (root / CURSOR_HOOKS).is_file():
            remaining = strip_hooks(load_json(root / CURSOR_HOOKS))
            empty = not (set(remaining) - {"version"})
            changes.append(
                FileChange(CURSOR_HOOKS, None if empty else dump_json(remaining), "PRISM hooks")
            )
        return [c for c in changes if not c.is_noop(root)]

    def status(self, root: Path) -> list[tuple[str, bool | None, str]]:
        out: list[tuple[str, bool | None, str]] = []
        rule = read_text(root / CURSOR_RULE)
        if rule is not None:
            out.append(("cursor rule", rule == cursor_rule(), ".cursor/rules/prism.mdc installed"))
        hooks = read_text(root / CURSOR_HOOKS)
        if hooks is not None:
            both = "prism hook session-start" in hooks and "prism hook post-edit" in hooks
            out.append(
                (
                    "cursor hooks",
                    True if both else None,
                    "sessionStart and afterFileEdit installed"
                    if both
                    else "not installed (optional)",
                )
            )
        return out


class AgentsMdIntegration(Integration):
    """Any agent that reads a root AGENTS.md: the generic fallback."""

    def __init__(self, name: str = "generic") -> None:
        self.name = name

    def detect(self, root: Path) -> bool:
        return False

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
