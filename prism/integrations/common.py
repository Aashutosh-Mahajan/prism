"""Content shared by all agent integrations: skills, instruction blocks, MCP entry."""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
SKILL_NAMES = ("prism-context", "prism-refresh", "prism-audit", "prism-decisions")

MCP_ENTRY = {"command": "prism", "args": ["mcp"]}

INSTRUCTION_BLOCK = """\
## PRISM code index

Use PRISM context supplied with the prompt directly; do not retrieve it again.
Otherwise, for unknown code use `prism task "<user request>"` (MCP: `prism_task`) once.
Architecture requests return a compact map; edits return source, local definitions, callers and tests.
Use returned evidence directly. If partial, read only `read_next` ranges; if weak, search narrowly.
Literal lists are exhaustive only when marked complete. Do not follow a good packet with a repo scan.
For a map explicitly use `--mode overview`; for source use `--mode code` (MCP: `mode`).
Known one-line edits need no broad orientation. Queries refresh the index.

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
