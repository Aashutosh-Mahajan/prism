"""Can the project's test command actually run in this checkout? Asked once, then cached.

A packet that says "Run: cd backend && python manage.py test" where Django is not installed
sends an agent hunting for an interpreter: in measured sessions that was dozens of shell commands
per edit (`where python`, `python --version`, `import django`). One cheap probe, cached until the
dependency files change, lets the packet say plainly how to check the change here instead.

Only what the command itself needs is probed, never installed: the test runner's module for
Python (`django` for `manage.py test`, `pytest` for pytest), the `node_modules` runner for
JavaScript, the `go` binary for Go. Anything else is assumed runnable; the probe only ever
withholds a command it has shown cannot start.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

PROBE_SECONDS = 10.0
CACHE_FILE = "verify-env.json"
# Files whose change can make a runner appear or disappear.
_MANIFESTS = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.cfg",
    "Pipfile.lock",
    "poetry.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "go.mod",
)
_JS_RUNNERS = ("jest", "vitest", "mocha")


def _needs(command: str) -> tuple[str, str] | None:
    """(kind, name) the command cannot start without, or None when nothing is known."""
    words = command.replace("&&", " ").split()
    if "manage.py" in words and "test" in words:
        return ("python", "django")
    if "pytest" in words:
        return ("python", "pytest")
    for runner in _JS_RUNNERS:
        if runner in words:
            return ("node", runner)
    if words[:2] == ["npm", "test"] or (words[:1] == ["npm"] and "test" in words):
        return ("node", "")
    if words[:2] == ["go", "test"]:
        return ("go", "go")
    return None


def _stamp(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in _MANIFESTS:
        for folder in (directory, directory.parent):
            try:
                digest.update(f"{folder / name}:{(folder / name).stat().st_mtime_ns}".encode())
            except OSError:
                continue
    digest.update(str((directory / "node_modules").is_dir()).encode())
    digest.update(str(shutil.which("python") or "").encode())
    return digest.hexdigest()[:16]


def _probe(directory: Path, kind: str, name: str) -> str:
    """'' when the runner is available, else a short reason."""
    if kind == "python":
        python = shutil.which("python") or shutil.which("python3")
        if python is None:
            return "no python on PATH"
        try:
            found = subprocess.run(
                [
                    python,
                    "-c",
                    f"import importlib.util,sys;sys.exit(importlib.util.find_spec({name!r}) is None)",
                ],
                cwd=directory,
                capture_output=True,
                timeout=PROBE_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""  # unknown is not proof that it cannot run
        return "" if found.returncode == 0 else f"{name} is not installed for the python on PATH"
    if kind == "node":
        modules = next(
            (
                d / "node_modules"
                for d in (directory, directory.parent)
                if (d / "node_modules").is_dir()
            ),
            None,
        )
        if modules is None:
            return "node_modules is not installed"
        if name and not any((modules / ".bin" / f"{name}{ext}").exists() for ext in ("", ".cmd")):
            return f"{name} is not installed in node_modules"
        return ""
    if kind == "go":
        return "" if shutil.which("go") else "go is not on PATH"
    return ""


def unrunnable(root: Path, command: str) -> str:
    """Why `command` cannot run in this checkout, or '' when it can (or that is unknown)."""
    need = _needs(command)
    if need is None:
        return ""
    directory = root
    if command.startswith("cd ") and " && " in command:
        directory = root / command[3:].split(" && ", 1)[0].strip().strip("'\"")
    if not directory.is_dir():
        return ""
    from prism.consent import cache_root

    cache = cache_root(root) / CACHE_FILE
    key = f"{command}|{_stamp(directory)}"
    try:
        known = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    if isinstance(known, dict) and key in known:
        return str(known[key])
    reason = _probe(directory, *need)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({key: reason}), encoding="utf-8")
    except OSError:
        pass
    return reason
