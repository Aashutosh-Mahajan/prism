"""Symbol-level call graph with best-effort static resolution.

Each edge carries a confidence:
  high   - resolved through a local definition or an explicit import
  medium - resolved through `self`/`cls`/`super()` into a base class
  low    - `obj.method()` matched by a unique method name across the repo
"""

from __future__ import annotations

import builtins

from prism.core.models import CallGraph, CallRef, Confidence, Edge, Symbol
from prism.graph.ranking import Ranker, pagerank
from prism.graph.symbol_table import SymbolTable

_BUILTINS = frozenset(dir(builtins))
_MAX_DEPTH = 6


class Resolver:
    def __init__(self, table: SymbolTable) -> None:
        self.table = table
        self.by_name: dict[str, list[str]] = {}
        for sid, sym in sorted(table.symbols.items()):
            if sym.kind in ("method", "function"):
                self.by_name.setdefault(sym.name, []).append(sid)
        self.bases: dict[str, list[str]] = {}
        for mod, pf in table.files.items():
            for ps in pf.symbols:
                if ps.kind == "class" and ps.bases:
                    cid = f"{mod}.{ps.qualname}"
                    resolved = [self.resolve_name(mod, b) for b in ps.bases]
                    self.bases[cid] = [r for r in resolved if r and r in table.symbols]

    def resolve_qualified(self, dotted: str, depth: int = 0) -> str | None:
        """Resolve an absolute dotted path, following re-exports through package scopes."""
        if depth > _MAX_DEPTH:
            return None
        if dotted in self.table.symbols:
            return dotted
        parts = dotted.split(".")
        for i in range(len(parts) - 1, 0, -1):
            mod = self.table.modules.find(".".join(parts[:i]))
            if mod is None:
                continue
            return self._lookup_in_module(mod, parts[i:], depth)
        # Directory packages (Go, Java): the name lives in one of the package's files.
        for i in range(len(parts) - 1, 0, -1):
            for mod in self.table.modules.find_package(".".join(parts[:i])):
                if parts[i] in self.table.scopes[mod].defs:
                    return self._lookup_in_module(mod, parts[i:], depth)
        return None

    def _lookup_in_module(self, mod: str, rest: list[str], depth: int) -> str | None:
        scope = self.table.scopes[mod]
        head, tail = rest[0], rest[1:]
        if head in scope.defs:
            candidate = ".".join([scope.defs[head], *tail])
            return candidate if candidate in self.table.symbols else None
        if head in scope.bindings:
            return self.resolve_qualified(".".join([scope.bindings[head], *tail]), depth + 1)
        for star in scope.star_imports:
            found = self.resolve_qualified(".".join([star, *rest]), depth + 1)
            if found:
                return found
        return None

    def resolve_name(self, mod: str, dotted: str) -> str | None:
        """Resolve a dotted expression as written inside module `mod`."""
        parts = dotted.split(".")
        scope = self.table.scopes[mod]
        head = parts[0]
        if head in scope.defs or head in scope.bindings or scope.star_imports:
            found = self._lookup_in_module(mod, parts, 0)
            if found or head in scope.defs or head in scope.bindings:
                return found
        # Same-package names need no import in Go and Java.
        for sibling in self.table.modules.package_of(mod):
            if sibling != mod and head in self.table.scopes[sibling].defs:
                return self._lookup_in_module(sibling, parts, 0)
        return None

    def method_in_class(self, cls: str, name: str, seen: set[str] | None = None) -> str | None:
        seen = seen if seen is not None else set()
        if cls in seen:
            return None
        seen.add(cls)
        candidate = f"{cls}.{name}"
        if candidate in self.table.symbols:
            return candidate
        for base in self.bases.get(cls, []):
            found = self.method_in_class(base, name, seen)
            if found:
                return found
        return None

    def resolve_call(
        self,
        sym: Symbol | None,
        mod: str,
        call: CallRef,
        local_types: dict[str, str] | None = None,
    ) -> tuple[str, Confidence] | None:
        parts = call.target.split(".")
        head = parts[0]
        if local_types and len(parts) == 2 and head in local_types:
            cls = self.resolve_name(mod, local_types[head])
            if cls and self.table.symbols[cls].kind == "class":
                found = self.method_in_class(cls, parts[1])
                if found:
                    return found, "medium"
        enclosing_class = self._enclosing_class(sym)
        if len(parts) == 1 and enclosing_class and self.table.files[mod].language == "java":
            # In Java an unqualified call inside a method is a call on the enclosing class.
            direct = f"{enclosing_class}.{head}"
            if direct in self.table.symbols:
                return direct, "high"
            found = self.method_in_class(enclosing_class, head)
            if found:
                return found, "medium"
        if head in ("self", "cls", "this") and enclosing_class and len(parts) == 2:
            direct = f"{enclosing_class}.{parts[1]}"
            if direct in self.table.symbols:
                return direct, "high"
            found = self.method_in_class(enclosing_class, parts[1])
            if found:
                return found, "medium"
            return None
        if head == "super()" and enclosing_class and len(parts) == 2:
            for base in self.bases.get(enclosing_class, []):
                found = self.method_in_class(base, parts[1])
                if found:
                    return found, "medium"
            return None
        resolved = self.resolve_name(mod, call.target)
        if resolved:
            return resolved, "high"
        if len(parts) == 1 and head in _BUILTINS:
            return None
        if len(parts) == 2 and head not in self.table.scopes[mod].bindings:
            candidates = self.by_name.get(parts[-1], [])
            if len(candidates) == 1 and not parts[-1].startswith("__"):
                return candidates[0], "low"
        return None

    def _enclosing_class(self, sym: Symbol | None) -> str | None:
        while sym is not None:
            if sym.kind == "class":
                return sym.id
            sym = self.table.symbols.get(sym.parent) if sym.parent else None
        return None


def build_call_graph(table: SymbolTable, ranker: Ranker = pagerank) -> CallGraph:
    resolver = Resolver(table)
    best: dict[tuple[str, str], Edge] = {}
    order: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2}
    unresolved = 0
    for mod, pf in sorted(table.files.items()):
        for ps in pf.symbols:
            sid = f"{mod}.{ps.qualname}"
            sym = table.symbols[sid]
            for call in ps.calls:
                result = resolver.resolve_call(sym, mod, call, ps.local_types)
                if result is None:
                    unresolved += 1
                    continue
                target, confidence = result
                if target == sid:
                    continue
                key = (sid, target)
                existing = best.get(key)
                if (
                    existing is None
                    or order[confidence] < order[existing.confidence]
                    or (confidence == existing.confidence and call.line < (existing.line or 0))
                ):
                    best[key] = Edge(sid, target, confidence, call.line)

    edges = [best[k] for k in sorted(best)]
    for sym in table.symbols.values():
        sym.calls = []
        sym.called_by = []
    for e in edges:
        table.symbols[e.source].calls.append(e.target)
        table.symbols[e.target].called_by.append(e.source)
    for sym in table.symbols.values():
        sym.calls.sort()
        sym.called_by.sort()
    ranks = ranker(table.symbols, ((e.source, e.target) for e in edges))
    for sid, sym in table.symbols.items():
        sym.rank = ranks.get(sid, 0.0)
    return CallGraph(edges=edges, unresolved=unresolved, rank=ranks)


def resolve_module_calls(table: SymbolTable, mod: str, calls: list[CallRef]) -> list[str]:
    """Resolve module-level calls (e.g. inside a `__main__` guard) to symbol ids."""
    resolver = Resolver(table)
    out: set[str] = set()
    for call in calls:
        result = resolver.resolve_call(None, mod, call)
        if result:
            out.add(result[0])
    return sorted(out)
