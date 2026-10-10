"""`prism diff`: the checked patch for a request, without the rest of the packet."""

from __future__ import annotations

from typing import Any

from prism.navigator import enrich
from prism.navigator.source_index import SourceIndex, SourceReader
from prism.navigator.store import IndexStore


def patch_for_request(store: IndexStore, query: str) -> dict[str, Any]:
    """{patch, apply} when a safe patch exists, else {patch: None, reason}."""
    from prism.navigator.task_pack import _evidence

    replacements = enrich.parse_replacements(query)
    if not replacements:
        return {
            "patch": None,
            "reason": "no_replacement",
        }
    with SourceIndex(store) as index:
        reader = SourceReader(store)
        evidence = _evidence(store, index, reader, query)
        patch = enrich.build_patch(store, reader, query, evidence)
    if isinstance(patch, str):
        return {
            "patch": None,
            "reason": patch,
        }
    return {"patch": patch, "apply": f"{enrich.APPLY_COMMAND} {patch['path']}"}
