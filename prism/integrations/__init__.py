"""Agent integrations. The core never imports these; `init`/`uninstall-integration` do."""

from __future__ import annotations

from pathlib import Path

from prism.core.errors import UserError
from prism.integrations.antigravity import AntigravityIntegration
from prism.integrations.base import FileChange, Integration, IntegrationOptions
from prism.integrations.claude_code import ClaudeCodeIntegration
from prism.integrations.codex import CodexIntegration
from prism.integrations.gemini import GeminiIntegration
from prism.integrations.git_hooks import GitHooksIntegration
from prism.integrations.other_agents import AgentsMdIntegration, CursorIntegration

AGENTS = ("claude-code", "cursor", "codex", "gemini", "antigravity", "generic")
# What each agent can do, so `init` only asks about what applies.
HAS_HOOKS = frozenset({"claude-code", "cursor", "codex", "gemini"})
HAS_MCP = frozenset({"claude-code", "cursor", "codex", "gemini", "antigravity"})


def get_integration(name: str) -> Integration:
    if name == "claude-code":
        return ClaudeCodeIntegration()
    if name == "cursor":
        return CursorIntegration()
    if name == "codex":
        return CodexIntegration()
    if name == "gemini":
        return GeminiIntegration()
    if name == "antigravity":
        return AntigravityIntegration()
    if name == "generic":
        return AgentsMdIntegration("generic")
    raise UserError(f"unknown agent '{name}'; choose one of: {', '.join(AGENTS)}, auto")


def detect_agents(root: Path) -> list[str]:
    detectable = ("claude-code", "cursor", "codex", "gemini", "antigravity")
    found = [name for name in detectable if get_integration(name).detect(root)]
    return found or ["generic"]


def all_integrations() -> list[Integration]:
    return [get_integration(name) for name in AGENTS]


def all_removals(root: Path) -> list[FileChange]:
    seen: set[str] = set()
    out: list[FileChange] = []
    integrations: list[Integration] = [*all_integrations(), GitHooksIntegration()]
    for integ in integrations:
        for change in integ.plan_removal(root):
            if change.path not in seen:
                seen.add(change.path)
                out.append(change)
    return out


__all__ = [
    "AGENTS",
    "HAS_HOOKS",
    "HAS_MCP",
    "FileChange",
    "GitHooksIntegration",
    "Integration",
    "IntegrationOptions",
    "all_integrations",
    "all_removals",
    "detect_agents",
    "get_integration",
]
