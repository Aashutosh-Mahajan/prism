"""`prism context`: a budgeted context pack for a symbol, file, module, or route.

Assembly rules (CLAUDE.md 8.2): the target's location and signature always
come first; neighbours are ranked by edge proximity x importance x call
confidence and greedily fitted to the token budget; every read-list item
carries a `why` so the agent can skip what's irrelevant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prism.core.tokens import estimate_tokens
from prism.navigator.impact import dependents
from prism.navigator.resolve import Target
from prism.navigator.store import IndexStore, SymbolRow

DEFAULT_BUDGET = 2000
MAX_LISTED = 10
CALL_CONTEXT = 3  # lines either side of a call site
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.8, "low": 0.5}


@dataclass
class _Item:
    file: str
    start: int
    end: int
    tokens: int
    why: str
    score: float
    ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "file": self.file,
            "lines": [self.start, self.end],
            "tokens_est": self.tokens,
            "why": self.why,
        }
        if self.ref:
            out["id"] = self.ref
        return out


def _slice_tokens(sym: SymbolRow, start: int, end: int) -> int:
    span = max(1, sym.end - sym.start + 1)
    return max(1, round(sym.tokens_est * (end - start + 1) / span))


def _read_source(store: IndexStore, path: str, start: int, end: int) -> str | None:
    try:
        lines = (store.root / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return "\n".join(lines[start - 1 : end])


def _norm_rank(store: IndexStore) -> float:
    top = store.top_symbols(1, public_only=False)
    return top[0].rank if top and top[0].rank > 0 else 1.0


def _fit(items: list[_Item], budget: int, reserved: int) -> tuple[list[_Item], int]:
    chosen: list[_Item] = []
    used = reserved
    for item in items:
        if used + item.tokens <= budget:
            chosen.append(item)
            used += item.tokens
    return chosen, used


def _symbol_pack(
    store: IndexStore, target: Target, budget: int, depth: int, with_source: bool
) -> dict[str, Any]:
    sym = target.symbol
    assert sym is not None
    max_rank = _norm_rank(store)
    test_files = store.test_files()
    callers = store.callers(sym.id)
    callees = store.callees(sym.id)

    candidates: list[_Item] = []
    for link in callers:
        c = link.symbol
        line = link.line or c.start
        start, end = max(c.start, line - CALL_CONTEXT), min(c.end, line + CALL_CONTEXT)
        is_test = c.file in test_files
        weight = (0.9 if is_test else 1.0) * CONFIDENCE_WEIGHT.get(link.confidence, 0.5)
        candidates.append(
            _Item(
                c.file,
                start,
                end,
                _slice_tokens(c, start, end),
                "test" if is_test else "caller",
                weight * (0.5 + c.rank / max_rank),
                c.id,
            )
        )
    for link in callees:
        c = link.symbol
        end = c.end if c.tokens_est <= 300 else min(c.end, c.start + 12)
        candidates.append(
            _Item(
                c.file,
                c.start,
                end,
                _slice_tokens(c, c.start, end),
                "callee",
                0.85 * CONFIDENCE_WEIGHT.get(link.confidence, 0.5) * (0.5 + c.rank / max_rank),
                c.id,
            )
        )
    if depth >= 2:
        seen = {sym.id, *(link.symbol.id for link in callers)}
        for link in callers:
            for second in store.callers(link.symbol.id):
                c = second.symbol
                if c.id in seen:
                    continue
                seen.add(c.id)
                line = second.line or c.start
                start, end = max(c.start, line - CALL_CONTEXT), min(c.end, line + CALL_CONTEXT)
                candidates.append(
                    _Item(
                        c.file,
                        start,
                        end,
                        _slice_tokens(c, start, end),
                        "caller (2 hops)",
                        0.4 * (0.5 + c.rank / max_rank),
                        c.id,
                    )
                )
    candidates.sort(key=lambda i: (-i.score, i.file, i.start))

    target_item = _Item(
        sym.file, sym.start, sym.end, sym.tokens_est, "target", float("inf"), sym.id
    )
    source = None
    reserved = sym.tokens_est
    if with_source and sym.tokens_est * 2 <= budget:
        source = _read_source(store, sym.file, sym.start, sym.end)
        if source is not None:
            reserved += estimate_tokens(source)
    chosen, used = _fit(candidates, budget, reserved)

    blast = dependents(store, target, depth=3)
    blast_files = sorted(blast["files"], key=lambda f: (blast["files"][f], f))
    health = store.health_symbol(sym.id) or store.health_file(sym.file)
    tests = sorted(
        set(store.tests_for_symbol(sym.id))
        | {c.symbol.file for c in callers if c.symbol.file in test_files}
    )
    pack: dict[str, Any] = {
        "target": {
            "id": sym.id,
            "kind": sym.kind,
            "file": sym.file,
            "lines": [sym.start, sym.end],
            "signature": sym.signature,
        },
        "summary": sym.doc,
        "callers": [
            {"id": c.symbol.id, "file": c.symbol.file, "line": c.line, "confidence": c.confidence}
            for c in callers[:MAX_LISTED]
        ],
        "callees": [
            {
                "id": c.symbol.id,
                "file": c.symbol.file,
                "lines": [c.symbol.start, c.symbol.end],
                "confidence": c.confidence,
            }
            for c in callees[:MAX_LISTED]
        ],
        "omitted": {
            "callers": max(0, len(callers) - MAX_LISTED),
            "callees": max(0, len(callees) - MAX_LISTED),
        },
        "tests": tests or store.tests_for_file(sym.file),
        "co_changed": [f for f, _ in store.cochanged(sym.file)],
        "blast_radius": {"files": len(blast_files), "top": blast_files[:5]},
        "risk": {"score": health.get("risk", 0.0), "reasons": health.get("reasons", [])}
        if health
        else None,
        "open_findings": [f["id"] for f in store.open_findings(symbol=sym.id)],
        "read_list": [target_item.to_dict(), *(i.to_dict() for i in chosen)],
        "budget": {"requested": budget, "used": used},
    }
    routes = store.routes_for_handler(sym.id)
    if routes:
        pack["routes"] = [f"{r['method']} {r['path']}" for r in routes]
    config = store.config_reads(sym.id)
    if config:
        pack["config"] = config
    if sym.kind == "class":
        pack["members"] = [c.signature for c in store.children(sym.id)][:20]
    if source is not None:
        pack["source"] = source
    return pack


def _file_pack(store: IndexStore, target: Target, budget: int) -> dict[str, Any]:
    path = target.file
    module = target.module
    symbols = store.symbols_in_file(path)
    top_level = [s for s in symbols if s.parent is None]
    ranked = sorted(top_level, key=lambda s: (-s.rank, s.start))
    items = [
        _Item(s.file, s.start, s.end, s.tokens_est, f"{s.kind} in file", s.rank, s.id)
        for s in ranked
    ]
    chosen, used = _fit(items, budget, 0)
    chosen.sort(key=lambda i: i.start)
    blast = dependents(store, target, depth=3)
    blast_files = sorted(blast["files"], key=lambda f: (blast["files"][f], f))
    health = store.health_file(path)
    pack: dict[str, Any] = {
        "target": {
            "id": module.id if module else path,
            "kind": target.kind,
            "file": path,
            "language": store.file_language(path),
        },
        "summary": module.doc if module else "",
        "symbols": [
            {"id": s.id, "kind": s.kind, "lines": [s.start, s.end], "signature": s.signature}
            for s in ranked[:15]
        ],
        "omitted": {"symbols": max(0, len(ranked) - 15)},
        "imports": store.imports_of(module.id) if module else [],
        "imported_by": store.importers_of(module.id) if module else [],
        "external": store.externals_of(module.id) if module else [],
        "tests": store.tests_for_file(path),
        "co_changed": [f for f, _ in store.cochanged(path)],
        "blast_radius": {"files": len(blast_files), "top": blast_files[:5]},
        "risk": {"score": health.get("risk", 0.0), "reasons": health.get("reasons", [])}
        if health
        else None,
        "open_findings": [f["id"] for f in store.open_findings(file=path)],
        "read_list": [i.to_dict() for i in chosen],
        "budget": {"requested": budget, "used": used},
    }
    if module and module.is_package:
        pack["submodules"] = [
            m.id for m in store.modules_with_prefix(module.id) if m.id != module.id
        ][:20]
    return pack


def build_context(
    store: IndexStore,
    target: Target,
    budget: int = DEFAULT_BUDGET,
    depth: int = 1,
    with_source: bool = False,
) -> dict[str, Any]:
    if target.symbol is not None:
        pack = _symbol_pack(store, target, budget, depth, with_source)
        if target.route:
            pack["route"] = target.route
        return pack
    return _file_pack(store, target, budget)
