"""Navigator operations as plain functions returning JSON-ready dicts.

The CLI, MCP server, and viewer API all call these; no logic lives in the
surfaces themselves (CLAUDE.md Section 16).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prism.core.errors import NotFoundError, UserError
from prism.core.paths import AICONTEXT
from prism.navigator.context_pack import DEFAULT_BUDGET, build_context
from prism.navigator.impact import DEFAULT_DEPTH, impact
from prism.navigator.resolve import locate, resolve_target
from prism.navigator.store import IndexStore
from prism.status import compute_status
from prism.writers.activity import record_activity

BRIEF_BUDGET = 800  # `--detail brief`: sites and tests only, no map of callers


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
    session: str | None = None,
    use_cache: bool = True,
    detail: str = "full",
) -> dict[str, Any]:
    """One-call retrieval for a request. `seen` (a session's already-returned code ranges)
    makes repeats cost a reference line instead of the source again. Earlier sessions (other
    than `session`) that changed the same code are noted when the line fits the budget."""
    if mode == "verify":
        return _verify(store, query, budget, session)
    from prism.navigator.semantic import semantic_enabled
    from prism.navigator.task_pack import build_task
    from prism.writers.task_cache import (
        load_packet,
        packet_current,
        packet_path,
        save_packet,
        source_stamp,
    )

    if detail not in ("full", "brief"):
        raise UserError("task detail must be full or brief")
    if detail == "brief":
        budget = min(budget, BRIEF_BUDGET)
    stamp = source_stamp(store.root, store.manifest) if seen is None and use_cache else None
    # Answers with and without the embedding channel differ, so they are cached apart.
    cache_mode = f"{mode}+semantic" if semantic_enabled(store.root) else mode
    cache_mode = f"{cache_mode}+{detail}"
    path = packet_path(store.root, stamp, query.strip(), budget, cache_mode) if stamp else None
    cached = load_packet(path) if path else None
    pack = None
    if cached is not None and packet_current(store.root, store.manifest, cached[0], cached[1]):
        pack = cached[0]
        offered = (pack.get("patch") or {}).get("path")
        if offered and not (store.root / offered).is_file():
            pack = None  # the patch file was pruned: build the packet (and the patch) again
    if pack is None:
        pack = build_task(store, query, budget, seen, mode, detail)
        if (
            path
            and not pack.get("stale_sources")
            and source_stamp(store.root, store.manifest) == stamp
        ):
            save_packet(path, pack, store.root, store.manifest)
    record_activity(store.root, "task", [b["symbol"] for b in pack["blocks"] if b["symbol"]])
    return _with_history(store, pack, session)


def _verify(store: IndexStore, query: str, budget: int, session: str | None) -> dict[str, Any]:
    """After editing: the same request again, reduced to the exact sites that still match.

    It re-reads the working tree (queries refresh the index first), so a changed value that is
    still present anywhere shows up with its file and line, with no grep and no source blocks."""
    pack = op_task(store, query, max(budget, 1600), None, "auto", session, use_cache=False)
    # A generic phrase of the request ("minimum doctor age") legitimately remains after the edit.
    literals = [
        lit for lit in pack.get("literals", []) if lit["kind"] not in ("identifier", "phrase")
    ]
    remaining = sum(lit["total"] for lit in literals)
    verify: dict[str, Any] = {
        "query": pack.get("query", query),
        "intent": "verify",
        "blocks": [],
        "stale_sources": pack.get("stale_sources", 0),
        "confidence": pack.get("confidence", "low"),
        "sufficient": bool(literals) is False,
        "budget": pack["budget"],
    }
    if literals:
        verify["literals"] = literals
        verify["next"] = (
            f"{remaining} site(s) still match the old value: change the ones that belong to "
            "this request, then verify again."
        )
    else:
        verify["next"] = "No remaining matches of the old value(s) in the indexed source."
    from prism.navigator.task_pack import _size

    verify["budget"] = dict(pack["budget"], used_est=_size(verify))
    return verify


def _with_history(store: IndexStore, pack: dict[str, Any], session: str | None) -> dict[str, Any]:
    """Attach `history` lines (time-relative, so never part of a cached packet) within budget."""
    from prism.navigator.recall import related_history
    from prism.navigator.task_pack import _size

    blocks = pack["blocks"][:2]
    lines = related_history(
        store.root,
        {b["file"] for b in blocks},
        {b["symbol"] for b in blocks if b["symbol"]},
        exclude=session,
    )
    if not lines:
        return pack
    pack = dict(pack, budget=dict(pack["budget"]))
    while lines:
        pack["history"] = lines
        if _size(pack) <= pack["budget"]["requested"]:
            pack["budget"]["used_est"] = _size(pack)
            return pack
        lines = lines[:-1]
    del pack["history"]
    pack["budget"]["used_est"] = _size(pack)
    return pack


def op_knowledge(store: IndexStore, budget: int = 600) -> dict[str, Any]:
    """Inspect what is indexed locally without injecting the entire project."""
    from prism.navigator.knowledge import knowledge

    return knowledge(store, budget)


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
