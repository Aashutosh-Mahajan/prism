"""Detect the project's own test, type-check, lint, and coverage commands.

Detection only: PRISM never runs these. The audit skill decides which are
safe to run and asks the user about anything needing network/DB/Docker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _mentions(root: Path, pyproject: dict[str, Any], package: str) -> bool:
    project = pyproject.get("project", {})
    deps: list[str] = [str(d) for d in project.get("dependencies", [])]
    for group in project.get("optional-dependencies", {}).values():
        deps.extend(str(d) for d in group)
    for group in pyproject.get("dependency-groups", {}).values():
        deps.extend(str(d) for d in group if isinstance(d, str))
    for req in (
        "requirements-dev.txt",
        "requirements-test.txt",
        "requirements.txt",
        "dev-requirements.txt",
    ):
        path = root / req
        if path.is_file():
            deps.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return any(d.strip().lower().startswith(package) for d in deps)


def detect_toolchain(root: Path) -> list[dict[str, Any]]:
    """Ordered: tests -> type checker -> linter -> coverage (the audit's baseline order)."""
    py = _pyproject(root)
    tool = py.get("tool", {})
    out: list[dict[str, Any]] = []

    def add(kind: str, command: str, reason: str) -> None:
        out.append({"kind": kind, "command": command, "detected_from": reason})

    has_tests_dir = any((root / d).is_dir() for d in ("tests", "test"))
    if "pytest" in tool or (root / "pytest.ini").is_file() or (root / "conftest.py").is_file():
        add("test", "python -m pytest -q", "pytest configuration")
    elif _mentions(root, py, "pytest"):
        add("test", "python -m pytest -q", "pytest dependency")
    elif (root / "tox.ini").is_file():
        add("test", "tox", "tox.ini")
    elif has_tests_dir:
        add("test", "python -m pytest -q", "tests/ directory")

    if "mypy" in tool or (root / "mypy.ini").is_file() or (root / ".mypy.ini").is_file():
        add("typecheck", "python -m mypy .", "mypy configuration")
    elif "pyright" in tool or (root / "pyrightconfig.json").is_file():
        add("typecheck", "pyright", "pyright configuration")

    if "ruff" in tool or (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file():
        add("lint", "ruff check .", "ruff configuration")
    elif (root / ".flake8").is_file() or "flake8" in tool:
        add("lint", "flake8", "flake8 configuration")
    elif (root / ".pylintrc").is_file() or "pylint" in tool:
        add("lint", "pylint $(git ls-files '*.py')", "pylint configuration")

    if (
        out
        and out[0]["kind"] == "test"
        and "pytest" in out[0]["command"]
        and (
            _mentions(root, py, "pytest-cov")
            or "coverage" in tool
            or (root / ".coveragerc").is_file()
        )
    ):
        add("coverage", "python -m pytest -q --cov --cov-report=xml", "coverage configuration")

    pkg = root / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}) or {}
        except ValueError:
            scripts = {}
        for name, kind in (("test", "test"), ("typecheck", "typecheck"), ("lint", "lint")):
            if name in scripts:
                add(kind, f"npm run {name}", "package.json script")
    order = {"test": 0, "typecheck": 1, "lint": 2, "coverage": 3}
    return sorted(out, key=lambda t: (order.get(t["kind"], 9), t["command"]))
