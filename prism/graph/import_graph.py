"""Module-level import graph."""

from __future__ import annotations

import sys

from prism.core.models import Edge, ImportGraph, ModuleNode
from prism.graph.ranking import Ranker, pagerank
from prism.graph.symbol_table import SymbolTable, resolve_relative

_STDLIB: frozenset[str] = frozenset(getattr(sys, "stdlib_module_names", ()))


def build_import_graph(table: SymbolTable, ranker: Ranker = pagerank) -> ImportGraph:
    modules: dict[str, ModuleNode] = {}
    for mod, pf in sorted(table.files.items()):
        modules[mod] = ModuleNode(
            id=mod, file=pf.path, is_package=pf.is_package, doc=pf.doc, loc=pf.line_count
        )

    edge_set: set[tuple[str, str]] = set()
    external: dict[str, int] = {}
    for mod, pf in sorted(table.files.items()):
        node = modules[mod]
        ext: set[str] = set()
        for ref in pf.imports:
            base = resolve_relative(mod, pf.is_package, ref)
            target = None
            if ref.name and ref.name != "*":
                target = table.modules.find(f"{base}.{ref.name}")
            if target is None and base:
                target = table.modules.find(base)
            if target is None and base and ref.level == 0:
                # `import a.b.c` where only `a.b` is internal.
                parts = base.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    target = table.modules.find(".".join(parts[:i]))
                    if target:
                        break
            package = [] if target is not None or not base else table.modules.find_package(base)
            if target is None and ref.name and ref.name != "*" and not package:
                package = table.modules.find_package(f"{base}.{ref.name}")
            if target is not None:
                if target != mod:
                    edge_set.add((mod, target))
            elif package:
                edge_set.update((mod, m) for m in package if m != mod)
            elif ref.level == 0 and base:
                top = base.split(".")[0]
                if top not in _STDLIB and top != "__future__":
                    ext.add(top)
        node.external = sorted(ext)
        for name in ext:
            external[name] = external.get(name, 0) + 1

    edges = [Edge(s, t) for s, t in sorted(edge_set)]
    for e in edges:
        modules[e.source].imports.append(e.target)
        modules[e.target].imported_by.append(e.source)
    for node in modules.values():
        node.imports.sort()
        node.imported_by.sort()
    ranks = ranker(modules, ((e.source, e.target) for e in edges))
    for mod, node in modules.items():
        node.rank = ranks.get(mod, 0.0)
    return ImportGraph(modules=modules, edges=edges, external=dict(sorted(external.items())))
