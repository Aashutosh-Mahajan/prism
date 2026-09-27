"""`prism impact`: what could break if a target changes, and which tests to run."""

from __future__ import annotations

from typing import Any

from prism.graph.blast import reverse_bfs
from prism.navigator.resolve import Target
from prism.navigator.store import IndexStore

DEFAULT_DEPTH = 3
NODE_CAP = 500
SHOW_PER_LEVEL = 15


def _reverse_calls(store: IndexStore) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for src, dst, _ in store.call_edges():
        rev.setdefault(dst, []).append(src)
    return rev


def _reverse_imports(store: IndexStore) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for src, dst in store.import_edges():
        rev.setdefault(dst, []).append(src)
    return rev


def dependents(store: IndexStore, target: Target, depth: int = DEFAULT_DEPTH) -> dict[str, Any]:
    """Symbol- and file-level dependents by distance (the raw data behind `impact`)."""
    sym_dist: dict[str, int] = {}
    file_dist: dict[str, int] = {}
    if target.symbol is not None:
        seeds = [target.symbol.id, *(c.id for c in store.children(target.symbol.id))]
        sym_dist = reverse_bfs(seeds, _reverse_calls(store), depth, NODE_CAP)
    else:
        seeds = [s.id for s in store.symbols_in_file(target.file)]
        sym_dist = reverse_bfs(seeds, _reverse_calls(store), depth, NODE_CAP)
        if target.module is not None:
            mod_dist = reverse_bfs([target.module.id], _reverse_imports(store), depth, NODE_CAP)
            for mid, d in mod_dist.items():
                m = store.module(mid)
                if m:
                    file_dist[m.file] = min(d, file_dist.get(m.file, d))
    for sid, d in sym_dist.items():
        s = store.symbol(sid)
        if s and s.file != target.file:
            file_dist[s.file] = min(d, file_dist.get(s.file, d))
    file_dist.pop(target.file, None)
    return {"symbols": sym_dist, "files": file_dist}


def impact(store: IndexStore, target: Target, depth: int = DEFAULT_DEPTH) -> dict[str, Any]:
    deps = dependents(store, target, depth)
    sym_dist: dict[str, int] = deps["symbols"]
    file_dist: dict[str, int] = deps["files"]
    test_files = store.test_files()

    tests: set[str] = set()
    if target.symbol is not None:
        tests.update(store.tests_for_symbol(target.symbol.id))
    tests.update(store.tests_for_file(target.file))
    for sid in sym_dist:
        tests.update(store.tests_for_symbol(sid))
    for path in file_dist:
        if path in test_files:
            tests.add(path)
        else:
            tests.update(store.tests_for_file(path))

    levels = []
    for d in range(1, depth + 1):
        syms = sorted(s for s, dist in sym_dist.items() if dist == d)
        files = sorted(f for f, dist in file_dist.items() if dist == d and f not in test_files)
        if syms or files:
            levels.append(
                {
                    "distance": d,
                    "symbols": syms[:SHOW_PER_LEVEL],
                    "files": files[:SHOW_PER_LEVEL],
                    "omitted": max(0, len(syms) - SHOW_PER_LEVEL)
                    + max(0, len(files) - SHOW_PER_LEVEL),
                }
            )
    risk = None
    if target.symbol is not None:
        risk = store.health_symbol(target.symbol.id)
    if risk is None:
        risk = store.health_file(target.file)
    return {
        "target": {"id": target.id, "kind": target.kind, "file": target.file},
        "dependents": levels,
        "totals": {
            "symbols": len(sym_dist),
            "files": len([f for f in file_dist if f not in test_files]),
            "capped": len(sym_dist) >= NODE_CAP,
        },
        "tests": sorted(tests),
        "risk": {"score": risk.get("risk", 0.0), "reasons": risk.get("reasons", [])}
        if risk
        else None,
    }
