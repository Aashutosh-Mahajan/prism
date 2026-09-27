"""Agent integrations. The core never imports these; `init`/`uninstall-integration` do."""

from __future__ import annotations

from pathlib import Path

from prism.core.errors import UserError
from prism.integrations.base import FileChange, Integration, IntegrationOptions
from prism.integrations.claude_code import ClaudeCodeIntegration
from prism.integrations.git_hooks import GitHooksIntegration
from prism.integrations.other_agents import AgentsMdIntegration, CursorIntegration

AGENTS = ("claude-code", "cursor", "codex", "generic")


def get_integration(name: str) -> Integration:
    if name == "claude-code":
        return ClaudeCodeIntegration()
    if name == "cursor":
        return CursorIntegration()
    if name in ("codex", "generic"):
        return AgentsMdIntegration(name)
    raise UserError(f"unknown agent '{name}'; choose one of: {', '.join(AGENTS)}, auto")


def detect_agents(root: Path) -> list[str]:
    found = [
        name for name in ("claude-code", "cursor", "codex") if get_integration(name).detect(root)
    ]
    return found or ["generic"]


def all_removals(root: Path) -> list[FileChange]:
    seen: set[str] = set()
    out: list[FileChange] = []
    integrations: list[Integration] = [
        ClaudeCodeIntegration(),
        CursorIntegration(),
        AgentsMdIntegration("codex"),
        GitHooksIntegration(),
    ]
    for integ in integrations:
        for change in integ.plan_removal(root):
            if change.path not in seen:
                seen.add(change.path)
                out.append(change)
    return out


__all__ = [
    "AGENTS",
    "FileChange",
    "GitHooksIntegration",
    "Integration",
    "IntegrationOptions",
    "all_removals",
    "detect_agents",
    "get_integration",
]
