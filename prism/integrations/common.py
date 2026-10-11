"""Content shared by all agent integrations: skills, instruction blocks, MCP entry."""

from __future__ import annotations

import re
from pathlib import Path

from prism.instructions import CONSENT, QUOTED_DATA, SHORT, long_form

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
SKILL_NAMES = ("prism-context", "prism-refresh", "prism-audit", "prism-decisions")

MCP_ENTRY = {"command": "prism", "args": ["mcp"]}


INSTRUCTION_BLOCK = long_form(False)
INSTRUCTION_BLOCK_MCP = long_form(True)


def instruction_block(mcp: bool) -> str:
    return long_form(mcp)


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
    text = (TEMPLATES / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    return text.replace("<!-- prism-shared-rules -->", f"{SHORT}\n{QUOTED_DATA}\n{CONSENT}")


def skill_files(name: str) -> list[tuple[str, str]]:
    """Every packaged resource, declared by an integration before it writes anything."""
    if name not in SKILL_NAMES:
        raise ValueError("unknown PRISM skill")
    directory = TEMPLATES / "skills" / name
    return [
        (
            path.relative_to(directory).as_posix(),
            skill_text(name) if path.name == "SKILL.md" else path.read_text(encoding="utf-8"),
        )
        for path in sorted(directory.rglob("*"), key=lambda path: path.as_posix())
        if path.is_file()
    ]


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
