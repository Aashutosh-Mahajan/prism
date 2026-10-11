"""Bounded, directed static paths with explicit relationship provenance."""

from __future__ import annotations

from collections import deque
from typing import Any

from prism.core.errors import UserError
from prism.navigator.resolve import resolve_target
from prism.navigator.source_index import SourceReader
from prism.navigator.store import IndexStore


def trace_path(
    store: IndexStore, source: str, target: str, depth: int = 4, max_nodes: int = 128
) -> dict[str, Any]:
    if not 1 <= depth <= 8 or not 2 <= max_nodes <= 1024:
        raise UserError("trace depth must be 1–8 and max_nodes 2–1024")
    start, goal = resolve_target(store, source), resolve_target(store, target)
    symbols = start.symbol is not None and goal.symbol is not None
    if not symbols and not (start.module and goal.module):
        raise UserError("trace needs two symbols or two modules")
    reader = SourceReader(store)
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(start.id, [])])
    visited = {start.id}
    limited = False
    path = None
    while queue:
        current, edges = queue.popleft()
        if current == goal.id:
            if reader.lines(goal.file) is not None:
                path = edges
            break
        if len(edges) >= depth:
            limited = True
            continue
        neighbors: list[dict[str, Any]]
        if symbols:
            origin = store.symbol(current)
            if origin is None or reader.lines(origin.file) is None:
                continue
            neighbors = [
                {
                    "from": current,
                    "to": link.symbol.id,
                    "relation": "calls",
                    "file": origin.file,
                    "line": link.line,
                    "confidence": link.confidence,
                    "resolution": link.resolution,
                    "provenance": "extracted"
                    if link.resolution == "resolved" and link.confidence == "high"
                    else "inferred",
                }
                for link in store.callees(current)
            ]
        else:
            module = store.module(current)
            if module is None or reader.lines(module.file) is None:
                continue
            neighbors = [
                {
                    "from": current,
                    "to": mid,
                    "relation": "imports",
                    "file": module.file,
                    "line": None,
                    "confidence": "high",
                    "resolution": "explicit_import",
                    "provenance": "extracted",
                }
                for mid in store.imports_of(current)
                if store.module(mid) is not None
            ]
        for edge in sorted(neighbors, key=lambda e: (e["provenance"] != "extracted", e["to"])):
            if edge["to"] in visited:
                continue
            if len(visited) >= max_nodes:
                limited = True
                continue
            visited.add(edge["to"])
            queue.append((edge["to"], [*edges, edge]))
    return {
        "source": start.id,
        "target": goal.id,
        "found": path is not None,
        "path": path or [],
        "searched_nodes": len(visited),
        "limited": limited or bool(reader.stale),
        "stale_files": sorted(reader.stale),
        "proof": "static relationships; not runtime execution proof",
    }


def render_trace(result: dict[str, Any]) -> str:
    lines = [f"Trace: {result['source']} → {result['target']}", result["proof"]]
    if not result["found"]:
        lines.append("No path found in the searched scope.")
    for edge in result["path"]:
        lines.append(
            f"{edge['from']} --{edge['relation']}--> {edge['to']} [{edge['provenance']}, {edge['confidence']}] {edge['file']}:{edge['line'] or 0}"
        )
    if result["limited"]:
        lines.append(
            "PARTIAL SEARCH: depth/node limit or stale source; absence is not proof of disconnection."
        )
    return "\n".join(lines)
