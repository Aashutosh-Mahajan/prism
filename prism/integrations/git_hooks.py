"""Git `post-commit` / `post-merge` / `post-checkout` hooks running `prism update --quiet`.

Hooks live in `.git/hooks/` (never committed). An existing hook keeps its
content; PRISM adds a marked block that is removed cleanly on uninstall.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from pathlib import Path

from prism.integrations.base import FileChange, Integration, IntegrationOptions, read_text

HOOK_NAMES = ("post-commit", "post-merge", "post-checkout")
START = "# >>> prism-managed >>>"
END = "# <<< prism-managed <<<"
BLOCK = (
    f"{START}\n"
    "# Keep the PRISM index fresh. Never blocks or fails git.\n"
    "if command -v prism >/dev/null 2>&1; then prism update --quiet >/dev/null 2>&1 || true; fi\n"
    f"{END}\n"
)
_BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n?", re.DOTALL)


def hooks_dir(root: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else (root / path)


class GitHooksIntegration(Integration):
    name = "git-hooks"

    def detect(self, root: Path) -> bool:
        return hooks_dir(root) is not None

    def plan(self, root: Path, options: IntegrationOptions) -> list[FileChange]:
        directory = hooks_dir(root)
        if directory is None:
            return []
        changes = []
        for name in HOOK_NAMES:
            path = directory / name
            existing = read_text(path)
            if existing is None or not existing.strip():
                content = "#!/bin/sh\n" + BLOCK
            elif START in existing:
                content = _BLOCK_RE.sub(BLOCK, existing, count=1)
            else:
                content = existing.rstrip("\n") + "\n\n" + BLOCK
            change = FileChange(_rel(root, path), content, f"git {name} hook: prism update")
            if not change.is_noop(root):
                changes.append(change)
        return changes

    def plan_removal(self, root: Path) -> list[FileChange]:
        directory = hooks_dir(root)
        if directory is None:
            return []
        changes = []
        for name in HOOK_NAMES:
            path = directory / name
            existing = read_text(path)
            if existing is None or START not in existing:
                continue
            remaining = _BLOCK_RE.sub("", existing).rstrip("\n")
            empty = remaining.strip() in ("", "#!/bin/sh")
            changes.append(
                FileChange(
                    _rel(root, path), None if empty else remaining + "\n", f"git {name} hook"
                )
            )
        return changes


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def make_executable(root: Path, changes: list[FileChange]) -> None:
    for change in changes:
        if change.content is not None and "/hooks/" in change.path.replace("\\", "/"):
            target = change.resolve(root)
            with contextlib.suppress(OSError):
                target.chmod(target.stat().st_mode | 0o111)
