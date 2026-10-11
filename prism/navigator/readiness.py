"""Explain the evidence behind readiness without pretending it is a probability."""

from __future__ import annotations

from typing import Any


def assess(pack: dict[str, Any]) -> dict[str, Any]:
    unresolved = []
    if pack.get("stale_sources"):
        unresolved.append("source_revision")
    if pack.get("search_limited"):
        unresolved.append("search_scope")
    if pack.get("read_next") or pack.get("read_ranges"):
        unresolved.append("source_ranges")
    if any(not lit["complete"] for lit in pack.get("literals", [])):
        unresolved.append("literal_coverage")
    if pack.get("callers_omitted"):
        unresolved.append("caller_inventory")
    if pack.get("test_warning"):
        unresolved.append("test_mapping")
    if pack.get("patch") and pack.get("sufficient"):
        basis = "checked_mechanical_patch"
    elif pack.get("overview"):
        basis = "selective_static_map"
    elif pack.get("sufficient"):
        basis = "retrieved_source_and_scope"
    else:
        basis = "candidates_only"
    return {"basis": basis, "unresolved": unresolved, "calibrated": False}
