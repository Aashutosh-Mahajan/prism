# Module `prism.navigator.graphify`

<!-- prism:generated:facts -->
- Files: prism/navigator/graphify.py
- Docstring: Optional Graphify graph hints; PRISM remains the source and budget authority.
- Public API (by importance):
  - `graphify_hints(store: IndexStore, reader: SourceReader, query: str) -> list[GraphHint]` — Load only an explicitly configured local export; never auto-install or generate it. (prism/navigator/graphify.py:220)
  - `class GraphHint` (prism/navigator/graphify.py:39)
  - `class GraphNode` (prism/navigator/graphify.py:30)
  - `class GraphifyGraph` — A bounded export loaded once per IndexStore and export file revision. (prism/navigator/graphify.py:47)
- Depends on: `prism`, `prism._vendor`, `prism.core`, `prism.navigator.source_index`, `prism.navigator.store`, `prism.navigator.text`
- Used by: `prism.navigator.store`, `prism.navigator.task_pack`
- Tests: tests/unit/test_graphify_hints.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Uses optional local Graphify exports as advisory retrieval hints. Prism verifies source locations and controls budgets. Configured external graphs bypass whole task-packet reuse so existing export verification stays active.
<!-- /prism:narrative:summary -->
