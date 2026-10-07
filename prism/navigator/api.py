"""Navigator operations as plain functions returning JSON-ready dicts.

The CLI, MCP server, and viewer API all call these; no logic lives in the
surfaces themselves (CLAUDE.md Section 16).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prism.core.errors import NotFoundError
from prism.core.paths import AICONTEXT
from prism.navigator.context_pack import DEFAULT_BUDGET, build_context
from prism.navigator.impact import DEFAULT_DEPTH, impact
from prism.navigator.resolve import locate, resolve_target
from prism.navigator.store import IndexStore
from prism.status import compute_status
from prism.writers.activity import record_activity


def op_locate(store: IndexStore, name: str, limit: int = 10) -> dict[str, Any]:
    candidates = locate(store, name, limit)
    if not candidates:
        from prism.navigator.resolve import _suggestions

        raise NotFoundError(f"nothing matches '{name}'", suggestions=_suggestions(store, name))
    record_activity(store.root, "locate", [c.id for c in candidates[:5]])
    return {"query": name, "candidates": [c.to_dict() for c in candidates]}


def op_context(
    store: IndexStore,
    target: str,
    budget: int = DEFAULT_BUDGET,
    depth: int = 1,
    with_source: bool = False,
) -> dict[str, Any]:
    resolved = resolve_target(store, target)
    pack = build_context(store, resolved, budget=budget, depth=depth, with_source=with_source)
    record_activity(store.root, "context", [resolved.id])
    return pack


def op_task(
    store: IndexStore,
    query: str,
    budget: int = 2000,
    seen: set[tuple[str, int, int]] | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """One-call retrieval for a request. `seen` (a session's already-returned code ranges)
    makes repeats cost a reference line instead of the source again."""
    from prism.navigator.task_pack import build_task

    pack = build_task(store, query, budget, seen, mode)
    record_activity(store.root, "task", [b["symbol"] for b in pack["blocks"] if b["symbol"]])
    return pack


def op_impact(store: IndexStore, target: str, depth: int = DEFAULT_DEPTH) -> dict[str, Any]:
    resolved = resolve_target(store, target)
    result = impact(store, resolved, depth)
    record_activity(store.root, "impact", [resolved.id])
    return result


def op_search(
    store: IndexStore, query: str, limit: int = 10, semantic: bool = False, embedder: Any = None
) -> dict[str, Any]:
    if semantic:
        from prism.navigator.semantic import get_embedder, hybrid_search, semantic_model

        raw = hybrid_search(
            store, query, limit, embedder or get_embedder(semantic_model(store.root))
        )
    else:
        raw = store.search(query, limit)
    hits = []
    for hit in raw:
        entry: dict[str, Any] = {"id": hit.ref, "kind": hit.kind, "score": hit.score}
        if hit.kind == "symbol":
            sym = store.symbol(hit.ref)
            if sym:
                entry.update(
                    kind=sym.kind,
                    file=sym.file,
                    lines=[sym.start, sym.end],
                    snippet=sym.doc or sym.signature,
                )
        elif hit.kind == "module":
            mod = store.module(hit.ref)
            if mod:
                entry.update(file=mod.file, lines=None, snippet=mod.doc)
        elif hit.kind == "route":
            entry.update(file=None, lines=None, snippet=hit.ref)
        elif hit.kind == "decision":
            entry.update(
                file=f"{AICONTEXT}/decisions/{hit.ref}.md",
                lines=None,
                snippet="architecture decision",
            )
        else:
            entry.update(file=hit.ref, lines=None, snippet="")
        hits.append(entry)
    record_activity(store.root, "search", [h["id"] for h in hits[:5]])
    return {"query": query, "hits": hits, "mode": "hybrid" if semantic else "bm25"}


def op_module(store: IndexStore, name: str) -> dict[str, Any]:
    modules_dir = store.root / AICONTEXT / "modules"
    available = sorted(p.stem for p in modules_dir.glob("*.md")) if modules_dir.is_dir() else []
    chosen = None
    if name in available:
        chosen = name
    else:
        # The group containing a module, or a unique suffix match.
        containing = [g for g in available if name.startswith(g + ".")]
        suffix = [g for g in available if g.endswith("." + name)]
        pool = sorted(containing, key=len, reverse=True)[:1] or suffix
        if len(pool) == 1:
            chosen = pool[0]
        elif len(pool) > 1:
            from prism.core.errors import AmbiguousTargetError

            raise AmbiguousTargetError(f"'{name}' matches several modules", candidates=pool)
    if chosen is None:
        import difflib

        raise NotFoundError(
            f"no module summary for '{name}'",
            suggestions=difflib.get_close_matches(name, available, n=5, cutoff=0.4)
            or available[:10],
        )
    text = (modules_dir / f"{chosen}.md").read_text(encoding="utf-8")
    record_activity(store.root, "module", [chosen])
    return {"module": chosen, "text": text}


def freshness_line(root: Path) -> str:
    report = compute_status(root)
    parts = ["PRISM"]
    if not report.indexed:
        parts.append("no index yet")
    elif report.fresh:
        parts.append("index fresh")
    else:
        parts.append(f"{report.changed} files changed since last update — run `prism update`")
    if report.stale_sections and _has_narrative(root):
        parts.append(
            "stale AGENTS.md sections: "
            + ", ".join(report.stale_sections)
            + " — run the prism-refresh skill"
        )
    if report.audit and report.audit["open"]:
        parts.append(f"{report.audit['open']} open audit findings")
    return " · ".join(parts)


def _has_narrative(root: Path) -> bool:
    """Staleness only matters for narrative someone chose to write; placeholders cannot go stale."""
    from prism.writers.agents_md import written_narrative

    path = root / AICONTEXT / "AGENTS.md"
    return path.is_file() and bool(written_narrative(path.read_text(encoding="utf-8")))


def op_brief(root: Path, full: bool = False) -> dict[str, Any]:
    from prism.writers.agents_md import compact_brief

    path = root / AICONTEXT / "AGENTS.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "brief": text if full else compact_brief(text),
        "freshness": freshness_line(root),
        "compact": not full,
    }
