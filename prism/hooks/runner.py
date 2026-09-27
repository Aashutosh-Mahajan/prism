"""Host-agent hooks: `prism hook session-start` and `prism hook post-edit`.

Contract (CLAUDE.md 12.2): always exit 0, finish fast, never print errors
into the agent's context, and do nothing unless PRISM is enabled for this
user and not paused. Errors go to `.aicontext/cache/hook.log`.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prism.consent import RepoState, repo_state
from prism.core.paths import AICONTEXT, find_repo_root
from prism.discovery import detect_language
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
        from prism.lifecycle import update
        from prism.navigator.api import freshness_line
        from prism.status import compute_status

        report = compute_status(root)
        note = ""
        catching_up = report.indexed and 0 < report.changed <= MAX_CATCHUP_FILES
        if catching_up and not _run_bounded(root, lambda: update(root), SESSION_START_BUDGET):
            note = " (catch-up still running; results may lag briefly)"
        brief_path = root / AICONTEXT / "AGENTS.md"
        brief = brief_path.read_text(encoding="utf-8").rstrip() if brief_path.is_file() else ""
        if not report.indexed:
            return "PRISM is enabled here but the index has not been built. Ask the user before running `prism scan`."
        return f"{brief}\n\n{freshness_line(root)}{note}\n"
    except BaseException:
        _log(root, "session-start failed:\n" + traceback.format_exc())
        return ""


def _edited_path(payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def post_edit(raw_stdin: str) -> None:
    payload = parse_payload(raw_stdin)
    root = _root_from(payload)
    try:
        if _state(root) is not RepoState.ENABLED:
            return
        edited = _edited_path(payload)
        files: list[str] | None = None
        if edited:
            path = Path(edited)
            path = path if path.is_absolute() else root / path
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                return  # outside this repo
            if rel.startswith(AICONTEXT + "/"):
                return
            first = ""
            if detect_language(rel) is None:
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as fh:
                        first = fh.readline()
                except OSError:
                    first = ""
                if detect_language(rel, first) is None and not rel.endswith(
                    (".gitignore", ".prismignore", "pyproject.toml", "prism.toml")
                ):
                    return  # docs, data, etc. don't change the index
            files = [rel]
        from prism.lifecycle import update

        _run_bounded(root, lambda: update(root, files=files), POST_EDIT_BUDGET)
    except BaseException:
        _log(root, "post-edit failed:\n" + traceback.format_exc())
