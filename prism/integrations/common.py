"""Content shared by all agent integrations: skills, instruction blocks, MCP entry."""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
SKILL_NAMES = ("prism-context", "prism-refresh", "prism-audit", "prism-decisions")

MCP_ENTRY = {"command": "prism", "args": ["mcp"]}

INSTRUCTION_BLOCK = """\
## PRISM code index

PRISM context may already be in the prompt: use it as given, do not fetch it again.
Otherwise run `prism task "<user request>"` once (MCP: `prism_task`) and read only the ranges it lists.
A literal list marked "exhaustive" is complete: no grep for it. Follow its `Patch:`, `Twins:` and
`Next:` lines; for several searches at once use `prism find "a" "b"`.

If PRISM is not enabled or not installed, work normally. Never run `prism init`, `prism scan`,
`prism enable`, or `prism install --global` unless the user explicitly asks.
"""

# For installs that register the MCP server: some agents (Codex) load MCP tools lazily and only
# reach for a tool the instructions name, so the block must name it and not only the shell command.
INSTRUCTION_BLOCK_MCP = """\
## PRISM code index

PRISM context may already be in the prompt: use it as given, do not fetch it again.
Otherwise call the MCP tool `prism_task` (server `prism`) once with the user's request and read
only the ranges it lists. If your tools do not list it, search them for "prism"; the shell command
`prism task "<user request>"` gives the same answer.
A literal list marked "exhaustive" is complete: no grep for it. Follow its `Patch:`, `Twins:` and
`Next:` lines; `prism_find` runs several searches at once.

If PRISM is not enabled or not installed, work normally. Never run `prism init`, `prism scan`,
`prism enable`, or `prism install --global` unless the user explicitly asks.
"""


def instruction_block(mcp: bool) -> str:
    """The managed block for an install that does (`mcp`) or does not register the MCP server."""
    return INSTRUCTION_BLOCK_MCP if mcp else INSTRUCTION_BLOCK


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
