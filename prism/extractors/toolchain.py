"""Detect the project's own test, type-check, lint, and coverage commands.

One detector feeds both the brief's "Commands" line and the audit plan. Detection only:
PRISM never runs these. Monorepos are handled by looking for project markers in the
root and up to SUBPROJECT_DEPTH levels below it (e.g. `backend/manage.py`,
`frontend/app/package.json`); commands for a subproject are prefixed with `cd <dir> &&`
so an agent can run them exactly as written.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from prism.discovery.scanner import BUILTIN_IGNORED_DIRS

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

SUBPROJECT_DEPTH = 2
PY_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "manage.py")
MARKERS = (*PY_MARKERS, "package.json")
KIND_ORDER = {"test": 0, "typecheck": 1, "lint": 2, "coverage": 3}
_NO_TEST_SCRIPT = "no test specified"  # npm init's placeholder


def _pyproject(path: Path) -> dict[str, Any]:
    file = path / "pyproject.toml"
    if not file.is_file():
        return {}
    try:
        with file.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _mentions(path: Path, pyproject: dict[str, Any], package: str) -> bool:
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
        file = path / req
        if file.is_file():
            deps.extend(file.read_text(encoding="utf-8", errors="replace").splitlines())
    return any(d.strip().lower().startswith(package) for d in deps)


def _python(path: Path, is_root: bool) -> list[tuple[str, str, str]]:
    if not is_root and not any((path / m).is_file() for m in PY_MARKERS):
        return []
    py = _pyproject(path)
    tool = py.get("tool", {})
    out: list[tuple[str, str, str]] = []
    pytest_config = (
        "pytest" in tool or (path / "pytest.ini").is_file() or (path / "conftest.py").is_file()
    )
    django = (path / "manage.py").is_file() and not _mentions(path, py, "pytest-django")
    if pytest_config and not django:
        out.append(("test", "python -m pytest -q", "pytest configuration"))
    elif django:
        out.append(("test", "python manage.py test", "Django manage.py"))
    elif _mentions(path, py, "pytest"):
        out.append(("test", "python -m pytest -q", "pytest dependency"))
    elif (path / "tox.ini").is_file():
        out.append(("test", "tox", "tox.ini"))
    elif any((path / d).is_dir() for d in ("tests", "test")):
        out.append(("test", "python -m pytest -q", "tests/ directory"))

    if "mypy" in tool or (path / "mypy.ini").is_file() or (path / ".mypy.ini").is_file():
        out.append(("typecheck", "python -m mypy .", "mypy configuration"))
    elif "pyright" in tool or (path / "pyrightconfig.json").is_file():
        out.append(("typecheck", "pyright", "pyright configuration"))

    if "ruff" in tool or (path / "ruff.toml").is_file() or (path / ".ruff.toml").is_file():
        out.append(("lint", "ruff check .", "ruff configuration"))
    elif (path / ".flake8").is_file() or "flake8" in tool:
        out.append(("lint", "flake8", "flake8 configuration"))
    elif (path / ".pylintrc").is_file() or "pylint" in tool:
        out.append(("lint", "pylint $(git ls-files '*.py')", "pylint configuration"))

    if (
        out
        and out[0][0] == "test"
        and "pytest" in out[0][1]
        and (
            _mentions(path, py, "pytest-cov")
            or "coverage" in tool
            or (path / ".coveragerc").is_file()
        )
    ):
        out.append(
            ("coverage", "python -m pytest -q --cov --cov-report=xml", "coverage configuration")
        )
    return out


def _node(path: Path) -> list[tuple[str, str, str]]:
    pkg = path / "package.json"
    if not pkg.is_file():
        return []
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    scripts = data.get("scripts") or {}
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    out: list[tuple[str, str, str]] = []
    test = scripts.get("test")
    if isinstance(test, str) and _NO_TEST_SCRIPT not in test:
        out.append(("test", "npm run test", "package.json script"))
    elif "vitest" in deps:
        out.append(("test", "npx vitest run", "vitest dependency"))
    elif "jest" in deps:
        out.append(("test", "npx jest", "jest dependency"))
    for name, kind in (("typecheck", "typecheck"), ("lint", "lint")):
        if name in scripts:
            out.append((kind, f"npm run {name}", "package.json script"))
    return out


def project_dirs(root: Path) -> list[str]:
    """The root ("") plus nested folders that hold their own project markers."""
    found = [""]
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        depth = 0 if rel == "." else rel.count("/") + 1
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in BUILTIN_IGNORED_DIRS
            and not d.startswith(".")
            and not d.endswith(".egg-info")
        )
        if depth >= SUBPROJECT_DEPTH:
            dirnames[:] = []
        if depth and any(m in filenames for m in MARKERS):
            found.append(rel)
    return sorted(found)


def detect_toolchain(root: Path) -> list[dict[str, Any]]:
    """Ordered: tests -> type checker -> linter -> coverage (the audit's baseline order),
    root project first within each kind."""
    out: list[dict[str, Any]] = []
    for rel in project_dirs(root):
        path = root / rel if rel else root
        for kind, command, reason in [*_python(path, rel == ""), *_node(path)]:
            entry: dict[str, Any] = {"kind": kind, "command": command, "detected_from": reason}
            if rel:
                entry.update(command=f"cd {rel} && {command}", cwd=rel)
            out.append(entry)
    return sorted(out, key=lambda t: (KIND_ORDER.get(t["kind"], 9), t.get("cwd", ""), t["command"]))


def brief_commands(root: Path) -> dict[str, str]:
    """One command per kind and folder, for the brief (coverage is audit-only)."""
    commands: dict[str, str] = {}
    for tool in detect_toolchain(root):
        if tool["kind"] == "coverage":
            continue
        key = f"{tool['kind']} ({tool['cwd']})" if tool.get("cwd") else tool["kind"]
        commands.setdefault(key, tool["command"])
    return commands
