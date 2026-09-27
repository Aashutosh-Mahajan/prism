"""Blast radius: for every file and every called public symbol, the files that
transitively depend on it (capped). Used by context packs and risk."""

from __future__ import annotations

from prism.core.models import BlastRadius
from prism.extractors.base import Extractor, ExtractorContext
from prism.graph.blast import reverse_bfs

DEPTH = 3
CAP = 200
TOP = 5


class BlastRadiusExtractor(Extractor[BlastRadius]):
    name = "blast_radius"

    def run(self, ctx: ExtractorContext) -> BlastRadius:
        table = ctx.table
        rev_calls: dict[str, list[str]] = {}
        for e in ctx.call_graph.edges:
            rev_calls.setdefault(e.target, []).append(e.source)
        rev_imports: dict[str, list[str]] = {}
        for e in ctx.import_graph.edges:
            rev_imports.setdefault(e.target, []).append(e.source)
        file_of_module = {m.id: m.file for m in ctx.import_graph.modules.values()}

        def summarize(
            own_file: str, sym_dist: dict[str, int], mod_dist: dict[str, int]
        ) -> tuple[int, list[str]]:
            dist: dict[str, int] = {}
            for sid, d in sym_dist.items():
                f = table.symbols[sid].file
                if f != own_file:
                    dist[f] = min(d, dist.get(f, d))
            for mid, d in mod_dist.items():
                f = file_of_module[mid]
                if f != own_file:
                    dist[f] = min(d, dist.get(f, d))
            ordered = sorted(dist, key=lambda f: (dist[f], f))
            return len(ordered), ordered[:TOP]

        members: dict[str, list[str]] = {}
        for sid, sym in table.symbols.items():
            if sym.parent:
                members.setdefault(sym.parent, []).append(sid)
        symbols: dict[str, tuple[int, list[str]]] = {}
        for sid, sym in sorted(table.symbols.items()):
            seeds = [sid, *members.get(sid, [])] if sym.kind == "class" else [sid]
            if sym.visibility != "public" or not any(table.symbols[s].called_by for s in seeds):
                continue
            symbols[sid] = summarize(sym.file, reverse_bfs(seeds, rev_calls, DEPTH, CAP), {})

        by_file: dict[str, list[str]] = {}
        for sid, sym in table.symbols.items():
            by_file.setdefault(sym.file, []).append(sid)
        files: dict[str, tuple[int, list[str]]] = {}
        for mid, node in sorted(ctx.import_graph.modules.items()):
            sym_dist = reverse_bfs(by_file.get(node.file, []), rev_calls, DEPTH, CAP)
            mod_dist = reverse_bfs([mid], rev_imports, DEPTH, CAP)
            count, top = summarize(node.file, sym_dist, mod_dist)
            if count:
                files[node.file] = (count, top)
        return BlastRadius(files=files, symbols=symbols)
