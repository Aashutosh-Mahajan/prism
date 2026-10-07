"""`prism hook user-prompt`: put the code a request needs into context before the model's turn.

Retrieval as a tool costs a model turn that the agent has to remember to take, and a turn
re-sends the whole context. Retrieval as a hook costs none: the answer to `prism task` for the
user's own words arrives with the prompt. It only injects when it has something worth reading
(medium or high confidence), only code not already sent this session, and never more than a
small budget; for greetings, confirmations, slash commands and unrelated requests it says nothing.
"""

from __future__ import annotations

import re
import threading
import traceback
from typing import Any

from prism.consent import RepoState
from prism.hooks.runner import _log, _root_from, _spawn_update, _state, parse_payload

PROMPT_BUDGET = 1200  # tokens (chars/4); Codex sets aside long hook output past ~2,500
MAX_PROMPT_CHARS = 2000
MIN_WORDS = 4
TIME_BUDGET_SECONDS = 4.0
WARMUP_SECONDS = 120.0

_ACKNOWLEDGEMENT = re.compile(
    r"^(?:ok(?:ay)?|yes|no|yep|nope|sure|thanks?(?: you)?|continue|go ahead|proceed|do it|"
    r"done|lgtm|looks good|stop|retry|again)\b[\s.!?]*$",
    re.IGNORECASE,
)
_CODE_LIKE = re.compile(r"[A-Za-z0-9]+_[A-Za-z0-9_]+|[a-z][A-Z]|\w+\.\w+\(|/\w+\.\w{1,5}\b")
HEADER = (
    "PRISM looked up this request in the local index (below). Literal lists marked exhaustive "
    "cover the whole indexed source."
)


def should_retrieve(prompt: str) -> bool:
    """Is this prompt a request about the code, rather than chat, a command or a confirmation?"""
    text = prompt.strip()
    if not text or text.startswith(("/", "!")):
        return False
    if _ACKNOWLEDGEMENT.match(text):
        return False
    words = re.findall(r"[A-Za-z0-9_]+", text)
    return len(words) >= MIN_WORDS or bool(_CODE_LIKE.search(text))


def _enabled(root_config_extra: dict[str, Any]) -> bool:
    import os

    if os.environ.get("PRISM_PROMPT_CONTEXT") == "0":
        return False
    return root_config_extra.get("prompt_context", True) is not False


def _claim_warmup(root: Any) -> bool:
    """One warm-up at a time: a marker file younger than the longest plausible warm-up."""
    import os
    import time

    marker = root / ".aicontext" / "cache" / "warming"
    try:
        if time.time() - marker.stat().st_mtime < WARMUP_SECONDS:
            return False
    except OSError:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        return False
    return True


def _retrieve(
    root_text: str,
    prompt: str,
    session: str | None,
    budget: int,
    abandoned: threading.Event | None = None,
) -> str:
    from pathlib import Path

    from prism.navigator.api import op_task
    from prism.navigator.freshness import caches_ready, refresh_if_stale
    from prism.navigator.session import load_seen, save_seen
    from prism.navigator.store import IndexStore
    from prism.navigator.task_pack import render_task

    root = Path(root_text)
    refresh_if_stale(root, wait=1.5)
    if not caches_ready(root):
        # Building the caches takes longer than a hook may. Start that in the background and say
        # nothing this time; the next request finds them ready.
        if _claim_warmup(root):
            _spawn_update(root, None, warm_only=True)
        return ""
    store = IndexStore.open(root)
    try:
        seen = load_seen(root, session) if session else None
        pack = op_task(store, prompt, budget, seen)
        # Remember what was returned only if the hook is still waiting for it: a result nobody
        # received must not make a later answer skip code the agent has never seen.
        if seen is not None and session and not (abandoned and abandoned.is_set()):
            save_seen(root, session, seen)
    finally:
        store.close()
    if pack["confidence"] == "low" or not (pack["blocks"] or pack.get("literals")):
        return ""
    return f"{HEADER}\n{render_task(pack)}"


def user_prompt(raw_stdin: str) -> str:
    """Context to add for the submitted prompt (empty when there is nothing worth adding)."""
    payload = parse_payload(raw_stdin)
    root = _root_from(payload)
    try:
        if _state(root) is not RepoState.ENABLED:
            return ""
        from prism.config import load_config

        config = load_config(root)
        if not _enabled(config.extra):
            return ""
        prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")[:MAX_PROMPT_CHARS]
        if not should_retrieve(prompt):
            return ""
        raw_budget = config.extra.get("prompt_budget", PROMPT_BUDGET)
        budget = (
            raw_budget
            if isinstance(raw_budget, int) and 128 <= raw_budget <= 8000
            else PROMPT_BUDGET
        )
        session = payload.get("session_id")
        result: list[str] = []
        abandoned = threading.Event()

        def work() -> None:
            try:
                result.append(
                    _retrieve(
                        str(root),
                        prompt,
                        session if isinstance(session, str) else None,
                        budget,
                        abandoned,
                    )
                )
            except BaseException:
                _log(root, "user-prompt failed:\n" + traceback.format_exc())

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(TIME_BUDGET_SECONDS)
        if not result:
            abandoned.set()
            return ""
        return result[0]
    except BaseException:
        _log(root, "user-prompt failed:\n" + traceback.format_exc())
        return ""
