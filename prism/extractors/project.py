"""Project facts for the brief: name and the commands an agent should use."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism.extractors.base import Extractor, ExtractorContext


@dataclass(frozen=True)
class ProjectFacts:
    name: str
    commands: dict[str, str]
    dependencies: list[str]


def _declares(pyproject: dict[str, Any], package: str) -> bool:
    project = pyproject.get("project", {})
    deps: list[str] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        deps.extend(group)
    for group in pyproject.get("dependency-groups", {}).values():
        deps.extend(d for d in group if isinstance(d, str))
    return any(str(d).lower().startswith(package) for d in deps)


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


def detect_commands(root: Path, pyproject: dict[str, Any], has_tests: bool) -> dict[str, str]:
    tool = pyproject.get("tool", {})
    commands: dict[str, str] = {}
    if (
        "pytest" in tool
        or (root / "pytest.ini").is_file()
        or (root / "conftest.py").is_file()
        or _declares(pyproject, "pytest")
        or has_tests
    ):
        commands["test"] = "pytest"
    if "ruff" in tool or (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file():
        commands["lint"] = "ruff check ."
    elif (root / ".flake8").is_file():
        commands["lint"] = "flake8"
    if "mypy" in tool or (root / "mypy.ini").is_file():
        commands["typecheck"] = "mypy"
    return commands


class ProjectExtractor(Extractor[ProjectFacts]):
    name = "project"

    def run(self, ctx: ExtractorContext) -> ProjectFacts:
        name = ctx.pyproject.get("project", {}).get("name") or ctx.root.name
        has_tests = any(
            "tests" in pf.path.split("/") or pf.path.rsplit("/", 1)[-1].startswith("test_")
            for pf in ctx.table.files.values()
        )
        return ProjectFacts(
            name=str(name),
            commands=detect_commands(ctx.root, ctx.pyproject, has_tests),
            dependencies=declared_dependencies(ctx.root, ctx.pyproject),
        )
