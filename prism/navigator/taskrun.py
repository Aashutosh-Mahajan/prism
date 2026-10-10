"""`prism task` as a function: the CLI and the warm query process both call it.

Keeping it in one place is what makes the two answers byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prism.navigator import api as nav
from prism.navigator.session import load_seen, save_seen, session_id
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task


def run_task(
    root: Path,
    store: IndexStore,
    query: str,
    budget: int,
    mode: str,
    session: str | None,
    as_json: bool,
    detail: str = "full",
) -> str:
    """The text `prism task` prints for one request. `session` is the explicit id, if any."""
    sid = session_id(session, store.root)
    seen = load_seen(store.root, sid, store.manifest, query) if sid else None
    committed = set(seen) if seen is not None else None
    pack = nav.op_task(store, query, budget, seen, mode, sid, detail=detail)
    # Compact JSON: the packet's budget is measured on this form.
    text = (
        json.dumps(pack, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
        if as_json
        else render_task(pack)
    )
    if sid and seen is not None:
        save_seen(store.root, sid, seen, store.manifest, query, committed)
    if sid:
        from prism.writers.worklog import record_delivery, record_focus, record_request

        record_request(store.root, sid, query)
        record_delivery(store.root, sid, "cli", True)
        record_focus(store.root, sid, [b["symbol"] for b in pack["blocks"][:2] if b["symbol"]])
    return text


def open_fresh_store(root: Path) -> Any:
    """The working tree checked against the index (changed files updated), then opened."""
    from prism.navigator.freshness import refresh_if_stale

    refresh_if_stale(root)
    return IndexStore.open(root)
