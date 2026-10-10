"""The exact command that runs the tests a request touches, from the project's own toolchain."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from shlex import quote

from prism.extractors.toolchain import detect_toolchain


@lru_cache(maxsize=8)
def _tests(root: str) -> tuple[tuple[str, str], ...]:
    """(project directory, test command) pairs, deepest directory first."""
    found = [
        (str(t.get("cwd", "")), str(t["command"]))
        for t in detect_toolchain(Path(root))
        if t["kind"] == "test"
    ]
    return tuple(sorted(found, key=lambda item: -len(item[0])))


def run_command(root: Path, test_files: list[str]) -> str | None:
    """`cd backend && python -m pytest -q tests/test_a.py ...`, or None when no test command is known."""
    if not test_files:
        return None
    choices = _tests(root.resolve().as_posix())
    if not choices:
        return None
    chosen = next(
        (c for c in choices if c[0] and all(f.startswith(c[0] + "/") for f in test_files)), None
    ) or next((c for c in choices if not c[0]), None)
    if chosen is None:
        return None  # never strip a subproject prefix from unrelated test paths
    directory, command = chosen
    base = command.split(" && ", 1)[1] if " && " in command else command
    local = [f[len(directory) + 1 :] if directory else f for f in test_files]
    runner = base.split()
    appendable = "pytest" in runner or any(r in ("jest", "vitest") for r in runner)
    if runner[:1] == ["go"] or base.startswith("go test"):
        packages = sorted({"./" + (f.rsplit("/", 1)[0] if "/" in f else ".") for f in local})
        base, appendable, local = "go test", True, packages
    full = f"{base} {' '.join(quote(path) for path in local)}" if appendable else base
    return f"cd {quote(directory)} && {full}" if directory else full
