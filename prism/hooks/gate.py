"""The finish-time check for hosts whose `Stop` hook can send the agent back to work.

For a request that changes a value everywhere it appears ("from 23 to 25"), the prompt hook notes
that the answer was an exhaustive list. When the agent is about to stop, this hook re-runs the same
request in verify mode: if the old value is still in the code it sends the agent back once, with the
remaining lines; otherwise it says nothing and costs nothing. It protects the result, it does not
shorten the session.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

GATE_BUDGET = 900
MAX_PASSES = 1


def is_value_change(packet: str) -> bool:
    """Did the prompt hook deliver an exhaustive list of a value to change?"""
    return "(current value)" in packet and "exhaustive" in packet


def _path(root: Path, session: str) -> Path:
    from prism.consent import cache_root

    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]
    return cache_root(root) / "gate" / f"{digest}.json"


def arm(root: Path, session: str | None, query: str, packet: str) -> None:
    """Remember what this session was asked, if its answer was an exhaustive value list."""
    if not session or not is_value_change(packet):
        return
    path = _path(root, session)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"query": query, "passes": 0}), encoding="utf-8")
    except OSError:
        pass


def remaining_sites(root: Path, query: str) -> str | None:
    """The rendered verify result when the old value still appears after edits, else None."""
    from prism.navigator import api as nav
    from prism.navigator.freshness import refresh_if_stale
    from prism.navigator.store import IndexStore
    from prism.navigator.task_pack import render_task

    if refresh_if_stale(root, wait=2.0) == 0:
        return None  # nothing was edited, so there is nothing to verify
    store = IndexStore.open(root)
    try:
        pack = nav.op_task(store, query, GATE_BUDGET, None, "verify", None)
    finally:
        store.close()
    # Only the old value counts: a number or quantity named in the request. Words of the request
    # that legitimately stay (a comment about "the minimum age") must not send the agent back.
    pack["literals"] = [
        lit for lit in pack.get("literals", []) if lit["kind"] in ("number", "quantity")
    ]
    return render_task(pack) if pack["literals"] else None


def stop(raw_stdin: str) -> str:
    """`Stop` hook output for Claude Code and Codex: a block decision, or nothing."""
    try:
        from prism.consent import RepoState
        from prism.hooks.runner import _root_from, _state, parse_payload, session_of

        payload: dict[str, Any] = parse_payload(raw_stdin)
        if payload.get("stop_hook_active"):
            return ""  # already sent back once by a stop hook: never loop
        root = _root_from(payload)
        if _state(root) is not RepoState.ENABLED:
            return ""
        session = session_of(payload)
        if not session:
            return ""
        path = _path(root, session)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        if not isinstance(state, dict) or int(state.get("passes", 0)) >= MAX_PASSES:
            return ""
        text = remaining_sites(root, str(state.get("query", "")))
        if text is None:
            return ""
        state["passes"] = int(state.get("passes", 0)) + 1
        path.write_text(json.dumps(state), encoding="utf-8")
        return json.dumps(
            {"decision": "block", "reason": "PRISM verify before you finish:\n" + text},
            ensure_ascii=False,
        )
    except BaseException:
        return ""
