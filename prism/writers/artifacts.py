"""Convert an `Index` into the JSON documents stored in `.aicontext/`.

Pure functions: no I/O, no timestamps. Output ordering is fully determined
by the input so identical code produces identical bytes.
"""

from __future__ import annotations

from typing import Any

from prism import SCHEMA_VERSION
from prism.core.models import Index, Symbol


def _symbol_entry(sym: Symbol) -> dict[str, Any]:
    return {
        "id": sym.id,
        "kind": sym.kind,
        "module": sym.module,
        "file": sym.file,
        "lines": [sym.lines[0], sym.lines[1]],
        "signature": sym.signature,
        "doc": sym.doc,
        "visibility": sym.visibility,
        "decorators": sym.decorators,
        "parent": sym.parent,
        "calls": sym.calls,
        "called_by": sym.called_by,
        "rank": sym.rank,
        "tokens_est": sym.tokens_est,
    }


def symbols_doc(index: Index) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "symbols": [_symbol_entry(index.symbols[k]) for k in sorted(index.symbols)],
    }


def dependency_graph_doc(index: Index) -> dict[str, Any]:
    graph = index.import_graph
    return {
        "schema_version": SCHEMA_VERSION,
        "modules": [
            {
                "id": m.id,
                "file": m.file,
                "is_package": m.is_package,
                "doc": m.doc,
                "loc": m.loc,
                "imports": m.imports,
                "imported_by": m.imported_by,
                "external": m.external,
                "rank": m.rank,
                "entry_point": m.entry_point,
                "community": m.community,
            }
            for m in (graph.modules[k] for k in sorted(graph.modules))
        ],
        "edges": [{"from": e.source, "to": e.target} for e in graph.edges],
        "external": graph.external,
        "declared_dependencies": index.declared_dependencies,
        "entry_points": [
            {
                "kind": ep.kind,
                "module": ep.module,
                "file": ep.file,
                "symbol": ep.symbol,
                "name": ep.name,
            }
            for ep in index.entry_points
        ],
    }


def call_graph_doc(index: Index) -> dict[str, Any]:
    graph = index.call_graph
    return {
        "schema_version": SCHEMA_VERSION,
        "edges": [
            {"from": e.source, "to": e.target, "confidence": e.confidence, "line": e.line}
            for e in graph.edges
        ],
        "rank": dict(sorted(graph.rank.items())),
        "stats": {
            "edges": len(graph.edges),
            "unresolved_calls": graph.unresolved,
            "by_confidence": {
                c: sum(1 for e in graph.edges if e.confidence == c)
                for c in ("high", "medium", "low")
            },
        },
    }


def tests_map_doc(index: Index) -> dict[str, Any]:
    tm = index.tests_map
    return {
        "schema_version": SCHEMA_VERSION,
        "test_files": tm.test_files,
        "by_symbol": tm.by_symbol,
        "by_file": tm.by_file,
    }


def routes_doc(index: Index) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "routes": [
            {
                "method": r.method,
                "path": r.path,
                "handler": r.handler,
                "file": r.file,
                "line": r.line,
                "framework": r.framework,
            }
            for r in index.routes
        ],
    }


def models_doc(index: Index) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "models": [
            {
                "id": m.id,
                "file": m.file,
                "lines": list(m.lines),
                "framework": m.framework,
                "fields": [{"name": n, "type": t} for n, t in m.fields],
                "used_by": m.used_by,
            }
            for m in index.models
        ],
    }


def config_doc(index: Index) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "keys": [
            {
                "key": k.key,
                "kind": k.kind,
                "reads": [{"symbol": r.symbol, "file": r.file, "line": r.line} for r in k.reads],
            }
            for k in index.config
        ],
    }


def health_doc(index: Index) -> dict[str, Any]:
    health = index.health
    files = health.files if health else {}
    counts: dict[str, int] = {}
    for entry in files.values():
        for smell in entry.get("smells", []):  # type: ignore[attr-defined]
            counts[smell["kind"]] = counts.get(smell["kind"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "files": files,
        "symbols": health.symbols if health else {},
        "dead_code": [
            {
                "id": d.id,
                "kind": d.kind,
                "file": d.file,
                "lines": list(d.lines),
                "reason": d.reason,
                "confidence": d.confidence,
            }
            for d in index.dead_code
        ],
        "smell_counts": dict(sorted(counts.items())),
    }


def git_doc(index: Index) -> dict[str, Any]:
    git = index.git
    if git is None or not git.available:
        return {
            "schema_version": SCHEMA_VERSION,
            "available": False,
            "head": None,
            "commits_analyzed": 0,
            "churn": {},
            "owners": {},
            "last_changed": {},
            "co_change": [],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "head": git.head,
        "commits_analyzed": git.commits_analyzed,
        "churn": git.churn,
        "owners": {f: [{"author": a, "commits": n} for a, n in o] for f, o in git.owners.items()},
        "last_changed": git.last_changed,
        "co_change": [
            {"a": a, "b": b, "count": n, "strength": st} for a, b, n, st in git.co_change
        ],
    }


def blast_doc(index: Index) -> dict[str, Any]:
    blast = index.blast
    return {
        "schema_version": SCHEMA_VERSION,
        "files": {k: {"count": c, "top": t} for k, (c, t) in sorted(blast.files.items())}
        if blast
        else {},
        "symbols": {k: {"count": c, "top": t} for k, (c, t) in sorted(blast.symbols.items())}
        if blast
        else {},
    }


ARTIFACTS = {
    "symbols.json": symbols_doc,
    "dependency_graph.json": dependency_graph_doc,
    "call_graph.json": call_graph_doc,
    "tests_map.json": tests_map_doc,
    "routes.json": routes_doc,
    "models.json": models_doc,
    "config.json": config_doc,
    "health.json": health_doc,
    "git_intelligence.json": git_doc,
    "blast_radius.json": blast_doc,
}


def build_docs(index: Index) -> dict[str, dict[str, Any]]:
    return {name: builder(index) for name, builder in ARTIFACTS.items()}
