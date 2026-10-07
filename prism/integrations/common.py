"""Content shared by all agent integrations: skills, instruction blocks, MCP entry."""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
SKILL_NAMES = ("prism-context", "prism-refresh", "prism-audit", "prism-decisions")

MCP_ENTRY = {"command": "prism", "args": ["mcp"]}

INSTRUCTION_BLOCK = """\
## PRISM code index

This repo has a local code index. Start each task with `prism task "<request>"` (MCP: `prism_task`):
one call returns the matching code, every exact string match (exhaustive, so do not grep for those),
call sites and tests. Use `prism context <symbol>` or `prism impact <symbol>` only for follow-ups.
The index refreshes itself before each answer.

If it reports PRISM is not enabled or not installed, work normally. Never run `prism init`,
`prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks.
"""

GLOBAL_NOTE = """\
## PRISM
If a repo has `.aicontext/` and `prism status` shows PRISM enabled, use PRISM for navigation
(`prism task "<user request>"`, then targeted follow-ups) instead of scanning files.
Never run `prism init` or `prism scan` unless the user asks.
"""

GLOBAL_SUGGEST = """\
If a large repo has no `.aicontext/`, you may mention PRISM once (`prism init` builds a local code index),
but never run it yourself.
"""


def skill_text(name: str) -> str:
    return (TEMPLATES / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def skill_body(name: str) -> str:
    """Skill text without YAML frontmatter or the managed marker, for rules files."""
    text = skill_text(name)
    if text.startswith("---\n"):
        text = text.split("---\n", 2)[2]
    text = re.sub(r"<!-- prism-managed:[^>]*-->\n?", "", text)
    return text.strip() + "\n"


def skill_description(name: str) -> str:
    front = skill_text(name).split("---\n", 2)[1]
    for line in front.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    return ""
