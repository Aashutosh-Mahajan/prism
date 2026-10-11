"""Compact local decision search with explicit expansion and revision validity.

Adopts AgentMemory's compact-search/expand contract without its external runtime.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from prism.core.errors import UserError
from prism.navigator.text import tokenize
from prism.writers.decisions import get_decision, list_decisions


def validity(root: Path, decision: dict[str, Any]) -> str:
    if decision["status"] in {"superseded", "deprecated"}:
        return "inactive"
    evidence = decision.get("evidence", {})
    if not evidence:
        return "unverified"
    resolved = root.resolve()
    for file, expected in evidence.items():
        path = (root / file).resolve()
        if not path.is_relative_to(resolved):
            return "stale"
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return "stale"
        except OSError:
            return "stale"
    return "current"


def search_decisions(
    root: Path, query: str = "", limit: int = 10, expand_id: str | None = None
) -> dict[str, Any]:
    if not 1 <= limit <= 50:
        raise UserError("decision limit must be 1–50")
    if expand_id is not None:
        decision = get_decision(root, expand_id)
        return {
            "mode": "expanded",
            "decision": dict(decision, validity=validity(root, decision)),
            "note": "Decision history is context; verify against current code.",
        }
    wanted = set(tokenize(query))
    scored = []
    for decision in list_decisions(root):
        if decision["status"] in {"superseded", "deprecated"}:
            continue
        score = len(wanted & set(tokenize(decision["text"]))) + 2 * len(
            wanted & set(tokenize(decision["title"]))
        )
        if wanted and not score:
            continue
        scored.append((score, decision))
    scored.sort(key=lambda row: (-row[0], row[1]["id"]))
    results = [
        {k: d[k] for k in ("id", "title", "status", "date", "symbols", "file")}
        | {"score": score, "validity": validity(root, d)}
        for score, d in scored[:limit]
    ]
    return {
        "mode": "compact",
        "decisions": results,
        "total": len(scored),
        "truncated": len(scored) > limit,
        "next": "Expand a selected id with prism decision show or prism_decisions(expand_id=...).",
    }
