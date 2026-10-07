"""Host-agent hooks: `prism hook session-start` and `prism hook post-edit`.

Contract (CLAUDE.md 12.2): always exit 0, finish fast, never print errors
into the agent's context, and do nothing unless PRISM is enabled for this
user and not paused. Errors go to `.aicontext/cache/hook.log`.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prism.consent import RepoState, repo_state
from prism.core.paths import AICONTEXT, find_repo_root
from prism.writers.manifest import load_manifest

SESSION_START_BUDGET = 1.8  # seconds
POST_EDIT_BUDGET = 0.9
MAX_CATCHUP_FILES = 300
NOT_ENABLED_LINE = (
    "This repo has a PRISM index. PRISM is not enabled for you here; "
    "run `prism enable` if you want to use it."
)


def _log(root: Path, message: str) -> None:
    try:
        path = root / AICONTEXT / "cache" / "hook.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except OSError:
        pass


def parse_payload(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _root_from(payload: dict[str, Any]) -> Path:
    cwd = payload.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    return find_repo_root(start)


def _state(root: Path) -> RepoState:
    manifest = load_manifest(root)
    return repo_state(root, manifest.get("repo_id") if manifest else None)


def _update_quietly(root: Path, files: list[str] | None) -> None:
    """Update the index; another updater already running is not an error, it is doing the job."""
    from prism.incremental.lock import LockBusy
    from prism.lifecycle import update

    with contextlib.suppress(LockBusy):
        update(root, files=files, lock_wait=0.3)


def _run_bounded(root: Path, fn: Callable[[], object], budget: float) -> bool:
    """Run `fn` in a daemon thread for at most `budget` seconds. True if it finished."""
    done = threading.Event()

    def target() -> None:
        try:
            fn()
        except BaseException:
            _log(root, "update failed:\n" + traceback.format_exc())
        finally:
            done.set()

    threading.Thread(target=target, daemon=True).start()
    return done.wait(budget)


def session_start(raw_stdin: str) -> str:
    """Returns the text to inject into the agent's context (may be empty)."""
    payload = parse_payload(raw_stdin)
    root = _root_from(payload)
    try:
        state = _state(root)
        if state is RepoState.NOT_INITIALIZED or state is RepoState.PAUSED:
            return ""
        if state is RepoState.NOT_ENABLED:
            return NOT_ENABLED_LINE
        from prism.navigator.api import freshness_line
        from prism.status import compute_status

        report = compute_status(root)
        note = ""
        catching_up = report.indexed and 0 < report.changed <= MAX_CATCHUP_FILES
        if catching_up and not _run_bounded(
            root, lambda: _update_quietly(root, None), SESSION_START_BUDGET
        ):
            note = " (catch-up still running; results may lag briefly)"
        from prism.writers.agents_md import compact_brief

        brief_path = root / AICONTEXT / "AGENTS.md"
        brief = (
            compact_brief(brief_path.read_text(encoding="utf-8")).rstrip()
            if brief_path.is_file()
            else ""
        )
        if not report.indexed:
            return "PRISM is enabled here but the index has not been built. Ask the user before running `prism scan`."
        return f"{brief}\n\n{freshness_line(root)}{note}\n"
    except BaseException:
        _log(root, "session-start failed:\n" + traceback.format_exc())
        return ""


_PATCH_FILE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M
)


def edited_paths(payload: dict[str, Any]) -> list[str]:
    """Files an edit touched, whichever agent reported it.

    Claude Code and Gemini CLI send `tool_input.file_path`; Cursor's `afterFileEdit` sends
    `file_path` at the top level; Codex's `apply_patch` carries the patch text itself.
    """
    found: list[str] = []
    top = payload.get("file_path")
    if isinstance(top, str) and top:
        found.append(top)
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("file_path", "notebook_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                found.append(value)
        command = tool_input.get("command")
        patch = "\n".join(command) if isinstance(command, list) else command
        if isinstance(patch, str) and "*** " in patch:
            for match in _PATCH_FILE.finditer(patch):
                found.append(match.group(1) or match.group(2))
    return list(dict.fromkeys(found))


def _spawn_update(root: Path, files: list[str] | None, warm_only: bool = False) -> bool:
    """Start an index job in a detached process and return at once. False if it could not start.
    `warm_only` builds the query caches without updating anything."""
    import subprocess
    import sys

    flag = ["--warm"] if warm_only else []
    command = [sys.executable, "-m", "prism.hooks.update_job", *flag, str(root), *(files or [])]
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        detached, no_window = 0x00000008, 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
        options["creationflags"] = detached | no_window | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        subprocess.Popen(command, **options)
    except OSError:
        return False
    return True


def _relative_source_paths(root: Path, edited: list[str]) -> list[str] | None:
    """Repo-relative paths among `edited` that can change the index. None = nothing to do."""
    from prism.discovery import detect_language

    files: list[str] = []
    for name in edited:
        path = Path(name)
        path = path if path.is_absolute() else root / path
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue  # outside this repo
        if rel.startswith(AICONTEXT + "/"):
            continue
        if detect_language(rel) is None:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    first = fh.readline()
            except OSError:
                first = ""
            if detect_language(rel, first) is None and not rel.endswith(
                (".gitignore", ".prismignore", "pyproject.toml", "prism.toml")
            ):
                continue  # docs, data, etc. don't change the index
        files.append(rel)
    return files or None


def post_edit(raw_stdin: str, background: bool = False) -> None:
    """Update the index for the edited files. With `background`, hand the update to a detached
    process so the agent never waits; a query that arrives first waits on the update lock."""
    payload = parse_payload(raw_stdin)
    root = _root_from(payload)
    try:
        if _state(root) is not RepoState.ENABLED:
            return
        edited = edited_paths(payload)
        files: list[str] | None = None
        if edited:
            files = _relative_source_paths(root, edited)
            if files is None:
                return
        if background and _spawn_update(root, files):
            return
        _run_bounded(root, lambda: _update_quietly(root, files), POST_EDIT_BUDGET)
    except BaseException:
        _log(root, "post-edit failed:\n" + traceback.format_exc())
