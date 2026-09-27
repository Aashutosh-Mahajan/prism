"""Project facts for the brief: name and the commands an agent should use."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism.extractors.base import Extractor, ExtractorContext
from prism.extractors.toolchain import brief_commands


@dataclass(frozen=True)
class ProjectFacts:
    name: str
    commands: dict[str, str]
    dependencies: list[str]


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def declared_dependencies(root: Path, pyproject: dict[str, Any]) -> list[str]:
    """Runtime dependency names from pyproject.toml, requirements.txt, and package.json."""
    names: set[str] = set()
    project = pyproject.get("project", {})
    reqs: list[str] = [str(d) for d in project.get("dependencies", [])]
    poetry = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if isinstance(poetry, dict):
        reqs.extend(k for k in poetry if k.lower() != "python")
    req_file = root / "requirements.txt"
    if req_file.is_file():
        reqs.extend(
            line
            for line in req_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))
        )
    for req in reqs:
        m = _REQ_NAME.match(req)
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            names.update(str(k) for k in (data.get("dependencies") or {}))
        except (ValueError, AttributeError):
            pass
    return sorted(names)


def detect_commands(root: Path, has_tests: bool) -> dict[str, str]:
    """The brief's commands: the shared toolchain detector, plus pytest as a fallback when
    Python tests exist but nothing declares how to run them."""
    commands = brief_commands(root)
    if has_tests and not any(k == "test" or k.startswith("test (") for k in commands):
        commands["test"] = "python -m pytest -q"
    return commands


class ProjectExtractor(Extractor[ProjectFacts]):
    name = "project"

    def run(self, ctx: ExtractorContext) -> ProjectFacts:
        name = ctx.pyproject.get("project", {}).get("name") or ctx.root.name
        has_tests = any(
            pf.path.endswith(".py")
            and ("tests" in pf.path.split("/") or pf.path.rsplit("/", 1)[-1].startswith("test_"))
            for pf in ctx.table.files.values()
        )
        return ProjectFacts(
            name=str(name),
            commands=detect_commands(ctx.root, has_tests),
            dependencies=declared_dependencies(ctx.root, ctx.pyproject),
        )
