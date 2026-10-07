"""Skill consistency: shipped skills may only reference real commands, flags, tools, and fields.

`PLANNED` lists commands the skills describe that later roadmap phases will add.
When a command lands, remove it from `PLANNED`; the test fails if a command is
both implemented and still listed, so this list can only shrink.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import typer.main
from typer.core import TyperCommand, TyperGroup

from prism.cli import app
from prism.mcp.server import EXTRA_TOOLS, NAVIGATION_TOOLS

SKILLS = Path(__file__).parents[2] / "prism" / "templates" / "skills"
SCHEMAS = Path(__file__).parents[2] / "prism" / "schemas"
SKILL_NAMES = ["prism-audit", "prism-context", "prism-decisions", "prism-refresh"]

PLANNED: dict[str, str] = {}

# `prism <word>` inside backticks, e.g. `prism context <target>`.
COMMAND_RE = re.compile(r"`prism ([a-z][a-z-]*)")
SNIPPET_RE = re.compile(r"`(prism [^`]+)`")
MCP_RE = re.compile(r"`(prism_[a-z_]+)`")


def root_group() -> TyperGroup:
    group = typer.main.get_group(app)
    # Typer >=0.26 vendors Click; validate against Typer's own group on both
    # old and new releases, without weakening command/flag introspection.
    assert isinstance(group, TyperGroup)
    return group


def implemented_commands() -> set[str]:
    return set(root_group().commands)


def read(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def resolve(tokens: list[str]) -> tuple[TyperCommand | TyperGroup | None, list[str]]:
    """Walk `prism a b c --flag` down the click tree. Returns (command, remaining tokens)."""
    cmd: TyperCommand | TyperGroup = root_group()
    rest = tokens[1:]
    while isinstance(cmd, TyperGroup) and rest and not rest[0].startswith("-"):
        sub = cmd.commands.get(rest[0])
        if sub is None:
            return (None if cmd is root_group() else cmd), rest
        cmd, rest = sub, rest[1:]
    return cmd, rest


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_structure(name: str) -> None:
    text = read(name)
    assert text.startswith("---\n")
    front = text.split("---\n", 2)[1]
    assert f"name: {name}" in front
    assert "description:" in front
    assert "<!-- prism-managed" in text
    for heading in (
        "## Purpose",
        "## When to use",
        "## Preconditions",
        "## Procedure",
        "## Outputs",
        "## Guardrails",
    ):
        assert heading in text, heading


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skills_reference_only_known_commands(name: str) -> None:
    known = implemented_commands() | set(PLANNED)
    mentioned = set(COMMAND_RE.findall(read(name)))
    assert mentioned, "expected the skill to mention prism commands"
    assert mentioned <= known, f"unknown commands: {sorted(mentioned - known)}"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_subcommands_and_flags_exist(name: str) -> None:
    problems = []
    snippets: list[str] = []
    for snippet in SNIPPET_RE.findall(read(name)):
        # Shorthand like `prism audit record/update` names two commands.
        words = snippet.split()
        alt = next(
            (i for i, w in enumerate(words) if "/" in w and not w.startswith(("<", "-", "."))), None
        )
        if alt is not None and all(p.isidentifier() for p in words[alt].split("/")):
            snippets.extend(
                " ".join([*words[:alt], p, *words[alt + 1 :]]) for p in words[alt].split("/")
            )
        else:
            snippets.append(snippet)
    for snippet in snippets:
        tokens = snippet.replace("[", " ").replace("]", " ").split()
        if len(tokens) < 2 or tokens[1] in PLANNED:
            continue
        cmd, rest = resolve(tokens)
        if cmd is None:
            problems.append(f"{snippet}: unknown command")
            continue
        if isinstance(cmd, TyperGroup) and rest and not rest[0].startswith(("<", "-")):
            problems.append(f"{snippet}: unknown subcommand {rest[0]!r}")
            continue
        opts = {
            o for p in cmd.params for o in getattr(p, "opts", []) + getattr(p, "secondary_opts", [])
        }
        for tok in rest:
            if tok.startswith("--"):
                flag = tok.split("=")[0].rstrip(",")
                if flag not in opts:
                    problems.append(f"{snippet}: unknown flag {flag}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_mcp_tools_exist(name: str) -> None:
    tools = {"prism_status", *NAVIGATION_TOOLS, *EXTRA_TOOLS, "prism_graph_view_url"}
    unknown = set(MCP_RE.findall(read(name))) - tools
    assert not unknown, f"unknown MCP tools: {sorted(unknown)}"


def test_audit_skill_fields_match_schemas() -> None:
    text = read("prism-audit")
    plan_props = set(json.loads((SCHEMAS / "audit_plan.schema.json").read_text())["properties"])
    listed = set(re.findall(r"^\s+- `([a-z_]+)`:", text, re.MULTILINE))
    assert {"toolchain", "targets", "smells", "dead_code", "untested", "reverify"} <= listed
    assert listed <= plan_props, f"plan fields not in schema: {sorted(listed - plan_props)}"

    block = text.split("```json", 1)[1].split("```", 1)[0]
    finding_keys = set(re.findall(r'"([a-z_]+)":', block))
    schema = json.loads((SCHEMAS / "finding_input.schema.json").read_text())
    props = set(schema["properties"]) | set(schema["properties"]["evidence"]["properties"])
    assert finding_keys <= props, f"finding fields not in schema: {sorted(finding_keys - props)}"
    for enum_field in ("severity", "category", "confidence"):
        values = set(schema["properties"][enum_field]["enum"])
        line = next(ln for ln in block.splitlines() if f'"{enum_field}"' in ln)
        assert set(re.findall(r"[a-z_]+", line.split(":", 1)[1])) == values


def test_planned_list_only_shrinks() -> None:
    assert not (implemented_commands() & set(PLANNED)), "remove implemented commands from PLANNED"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skills_forbid_unasked_enablement(name: str) -> None:
    text = read(name)
    assert "prism init" in text and "prism enable" in text
    assert re.search(r"[Nn]ever (run|enable)", text)
