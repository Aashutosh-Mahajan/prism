# Module `prism.graph`

<!-- prism:generated:facts -->
- Files: prism/graph/__init__.py, prism/graph/blast.py, prism/graph/call_graph.py, prism/graph/communities.py, prism/graph/import_graph.py, prism/graph/ranking.py, prism/graph/symbol_table.py
- Docstring: Reverse-dependency traversal shared by `impact`, context packs, and `blast_radius.json`.
- Public API (by importance):
  - `build_call_graph(table: SymbolTable, ranker: Ranker = pagerank) -> CallGraph` (prism/graph/call_graph.py:147)
  - `pagerank(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, float]` — PageRank over a directed graph. Rank flows from source to target. (prism/graph/ranking.py:15)
  - `class Resolver` (prism/graph/call_graph.py:21)
  - `build_symbol_table(parsed: list[ParsedFile]) -> SymbolTable` (prism/graph/symbol_table.py:99)
  - `louvain(nodes: Iterable[str], edges: Iterable[tuple[str, str, float]]) -> dict[str, int]` — Community index per node (0 = largest community). Edges are treated as undirected. (prism/graph/communities.py:52)
  - `build_import_graph(table: SymbolTable, ranker: Ranker = pagerank) -> ImportGraph` (prism/graph/import_graph.py:14)
  - `visibility_for(module: str, qualname: str) -> Visibility` (prism/graph/symbol_table.py:14)
  - `resolve_relative(importer: str, importer_is_package: bool, ref: ImportRef) -> str` — Absolute dotted module named by an import (without the imported `name`). (prism/graph/symbol_table.py:19)
  - `resolve_module_calls(table: SymbolTable, mod: str, calls: list[CallRef]) -> list[str]` — Resolve module-level calls (e.g. inside a `__main__` guard) to symbol ids. (prism/graph/call_graph.py:189)
  - `reverse_bfs(seeds: Iterable[str], reverse: Mapping[str, Iterable[str]], max_depth: int = 3, cap: int = 500) -> dict[str, int]` — Nodes that (transitively) depend on `seeds`, mapped to their distance (1..max_depth). (prism/graph/blast.py:8)
  - `class ModuleIndex` — Lookup of internal module names with a unique-suffix fallback. (prism/graph/symbol_table.py:46)
  - `class ModuleScope` — Names bound at the top level of one module. (prism/graph/symbol_table.py:32)
  - … 2 more
- Depends on: `prism.core`
- Used by: `prism`, `prism.extractors`, `prism.navigator.impact`
- Tests: tests/integration/test_phase5.py, tests/unit/test_graph.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
