"""Accumulate drift per narrative section and mark sections stale (CLAUDE.md 9.2)."""

from __future__ import annotations

from typing import Any

from prism.drift.structural_diff import Change

MAX_CHANGES = 20
MAX_IDS = 30


def apply_drift(
    drift: dict[str, Any], changes: list[Change], threshold: int, sections_present: set[str]
) -> dict[str, Any]:
    """Return an updated `manifest["drift"]`. Only sections that exist are tracked."""
    sections: dict[str, Any] = {k: dict(v) for k, v in drift.get("sections", {}).items()}
    for change in changes:
        if change.weight <= 0 and change.kind != "import_edge":
            continue
        for name in change.sections:
            if name not in sections_present:
                continue
            entry = sections.setdefault(
                name, {"score": 0, "stale": False, "changes": [], "ids": []}
            )
            entry["score"] = int(entry.get("score", 0)) + change.weight
            if change.weight and len(entry["changes"]) < MAX_CHANGES:
                entry["changes"] = [*entry["changes"], change.description]
            for i in change.ids:
                if i not in entry["ids"] and len(entry["ids"]) < MAX_IDS:
                    entry["ids"] = [*entry["ids"], i]
            entry["stale"] = entry["score"] >= threshold
    for name in list(sections):
        if name not in sections_present:
            del sections[name]
    return {**drift, "threshold": threshold, "sections": dict(sorted(sections.items()))}


def reset_section(drift: dict[str, Any], name: str, when: str) -> dict[str, Any]:
    sections = {k: dict(v) for k, v in drift.get("sections", {}).items()}
    sections[name] = {"score": 0, "stale": False, "changes": [], "ids": [], "last_refresh": when}
    return {**drift, "sections": dict(sorted(sections.items()))}
