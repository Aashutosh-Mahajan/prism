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
            "reason": "the request has no explicit old -> new value "
            "(for example 'from 23 to 25' or 'rename old_name to new_name')",
        }
    with SourceIndex(store) as index:
        reader = SourceReader(store)
        evidence = _evidence(store, index, reader, query)
        patch = enrich.build_patch(store, reader, query, evidence)
    if patch is None:
        return {
            "patch": None,
            "reason": "the sites are not an exhaustive, current list, a new name already exists, "
            "or git rejected the diff; use prism task to see them and edit by hand",
        }
    return {"patch": patch, "apply": f"{enrich.APPLY_COMMAND} {patch['path']}"}
