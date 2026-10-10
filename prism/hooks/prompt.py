"""`prism hook user-prompt`: put the code a request needs into context before the model's turn.

Retrieval as a tool costs a model turn that the agent has to remember to take, and a turn
re-sends the whole context. Retrieval as a hook costs none: the answer to `prism task` for the
user's own words arrives with the prompt. It only injects when it has something worth reading
(medium or high confidence), only code not already sent this session, and never more than a
small budget; for greetings, confirmations, slash commands and unrelated requests it says nothing.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import traceback
from typing import Any

from prism.consent import RepoState
from prism.hooks.runner import _log, _root_from, _spawn_update, _state, parse_payload

PROMPT_BUDGET = 2000  # hard cap; ordinary complete requests still start at 1,200
INITIAL_PACKET_BUDGET = 1200
MAX_PROMPT_CHARS = 2000
MIN_WORDS = 4
# Installed hooks allow 20 s; a cold process under load (several agents on one machine) can need
# more than 8 s for a broad request.
TIME_BUDGET_SECONDS = 16.0
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


_LABEL = re.compile(
    r"(?im)^[ 	]*(?:user request|request|task|ticket|issue|goal)[ 	]*:[ 	]*"
)


def request_text(prompt: str) -> str:
    """The request itself when a templated prompt wraps it in boilerplate.

    Prompts built by scripts and trackers often open with generic instructions ("You are working
    in the repository ... follow conventions ...") and put the request after a `Task:` style
    label. Searching for the boilerplate dilutes the match, so retrieval uses what follows the
    last such label; a prompt without one is used as it is."""
    labels = list(_LABEL.finditer(prompt))
    if not labels:
        return prompt
    rest = prompt[labels[-1].end() :].strip()
    return rest if len(rest.split()) >= MIN_WORDS else prompt


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


def _overview_allowed(root: Any) -> bool:
    """May the hook add the architecture map for an "explain the project" request?

    On by default: that request is answered by the map. Off with `prompt_overview = false`."""
    try:
        from prism.config import load_config

        return load_config(root).extra.get("prompt_overview", True) is not False
    except Exception:
        return True


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
    inline_build: bool = False,
) -> str:
    from pathlib import Path

    from prism.core.tokens import estimate_tokens
    from prism.navigator.api import op_task
    from prism.navigator.freshness import caches_ready, refresh_if_stale
    from prism.navigator.session import load_seen, save_seen
    from prism.navigator.store import IndexStore
    from prism.navigator.task_pack import MIN_BUDGET, render_task

    packet_budget = budget - estimate_tokens(HEADER + "\n")
    if packet_budget < MIN_BUDGET:
        return ""  # a silent hook costs less than an over-budget packet

    root = Path(root_text)
    refresh_if_stale(root, wait=1.5)
    if not inline_build and not caches_ready(root):
        # Building the caches takes longer than a hook may. Start that in the background and say
        # nothing this time; the next request finds them ready. (A host that allows a long hook
        # asks for `inline_build`: the first answer is then worth waiting for.)
        if _claim_warmup(root):
            _spawn_update(root, None, warm_only=True)
        return ""
    store = IndexStore.open(root)
    try:
        seen = load_seen(root, session, store.manifest) if session else None
        # A slightly larger complete packet can avoid another model turn. Try the small
        # working set first, expanding only when the hard cap permits it. Do not remember
        # ranges from an attempt that was never delivered to the host.
        trial_seen = set(seen) if seen is not None else None
        first_budget = min(packet_budget, INITIAL_PACKET_BUDGET - estimate_tokens(HEADER + "\n"))
        pack = op_task(store, prompt, first_budget, trial_seen, session=session)
        if (
            not pack.get("sufficient")
            and pack["confidence"] != "low"
            and packet_budget > first_budget
            and not (abandoned and abandoned.is_set())
        ):
            expanded_seen = set(seen) if seen is not None else None
            expanded = op_task(store, prompt, packet_budget, expanded_seen, session=session)
            if expanded.get("sufficient"):
                pack, trial_seen = expanded, expanded_seen
        speaks_for_overview = bool(pack.get("overview")) and _overview_allowed(root)
        if pack["confidence"] == "low" or not (
            pack["blocks"] or pack.get("literals") or speaks_for_overview
        ):
            return ""
        result = f"{HEADER}\n{render_task(pack)}"
        if estimate_tokens(result) > budget or (abandoned and abandoned.is_set()):
            return ""
        # Remember what was returned only if the hook is still waiting for it: a result nobody
        # received must not make a later answer skip code the agent has never seen.
        if trial_seen is not None and session and not (abandoned and abandoned.is_set()):
            save_seen(root, session, trial_seen, store.manifest)
        if not (abandoned and abandoned.is_set()):
            from prism.writers.worklog import record_focus

            record_focus(root, session, [b["symbol"] for b in pack["blocks"][:2] if b["symbol"]])
        return result
    finally:
        store.close()


def user_prompt(
    raw_stdin: str, time_budget: float | None = None, inline_build: bool = False
) -> str:
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
        prompt = request_text(str(payload.get("prompt") or payload.get("user_prompt") or ""))[
            :MAX_PROMPT_CHARS
        ]
        from prism.hooks.runner import session_of
        from prism.writers.worklog import record_delivery, record_request

        session = session_of(payload)
        if not should_retrieve(prompt):
            record_delivery(root, session, "hook", False, "not a request about the code")
            return ""
        record_request(root, session, prompt)
        from prism.navigator.session import note_active_session

        note_active_session(root, session)
        raw_budget = config.extra.get("prompt_budget", PROMPT_BUDGET)
        budget = (
            raw_budget
            if isinstance(raw_budget, int) and 128 <= raw_budget <= 8000
            else PROMPT_BUDGET
        )
        result: list[str] = []
        abandoned = threading.Event()

        def work() -> None:
            try:
                result.append(
                    _retrieve(
                        str(root),
                        prompt,
                        session,
                        budget,
                        abandoned,
                        inline_build,
                    )
                )
            except sqlite3.DatabaseError:
                # A damaged disposable cache: drop it now so the next prompt is answered.
                from prism.navigator.cache_db import purge_disposable_caches

                purge_disposable_caches(root)
            except BaseException:
                _log(root, "user-prompt failed:\n" + traceback.format_exc())

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(TIME_BUDGET_SECONDS if time_budget is None else time_budget)
        if not result:
            abandoned.set()
            record_delivery(root, session, "hook", False, "timed out or still warming the caches")
            return ""
        record_delivery(
            root,
            session,
            "hook",
            bool(result[0]),
            "" if result[0] else "no confident match, so nothing was added",
        )
        if result[0]:
            from prism.hooks.gate import arm

            arm(root, session, prompt, result[0])  # a finish-time check, for a value change
        return result[0]
    except BaseException:
        _log(root, "user-prompt failed:\n" + traceback.format_exc())
        return ""
