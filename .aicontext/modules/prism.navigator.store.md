# Module `prism.navigator.store`

<!-- prism:generated:facts -->
- Files: prism/navigator/store.py
- Docstring: Read access to the index for every navigator query (CLI, MCP, viewer).
- Public API (by importance):
  - `class SymbolRow` (prism/navigator/store.py:25)
  - `class ModuleRow` (prism/navigator/store.py:46)
  - `class Link` — A call-graph neighbour: the symbol and the call-site line in the caller. (prism/navigator/store.py:56)
  - `class SearchHit` (prism/navigator/store.py:65)
  - `class IndexStore` (prism/navigator/store.py:76)
- Depends on: `prism`, `prism.core`, `prism.extractors`, `prism.navigator.cache_db`, `prism.navigator.graphify`, `prism.navigator.text`, `prism.writers`
- Used by: `prism`, `prism.hooks`, `prism.mcp`, `prism.narrator`, `prism.navigator.api`, `prism.navigator.context_pack`, `prism.navigator.freshness`, `prism.navigator.graphify`, `prism.navigator.impact`, `prism.navigator.overview`, `prism.navigator.resolve`, `prism.navigator.semantic`, `prism.navigator.source_index`, `prism.navigator.task_pack`, `prism.viewer.api`
- Tests: tests/benchmarks/agent_measure.py, tests/benchmarks/agent_prepare.py, tests/benchmarks/retrieval_economics.py, tests/benchmarks/retrieval_eval.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_audit.py, tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/integration/test_phase5.py, tests/unit/test_graphify_hints.py, tests/unit/test_navigator.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_task_retrieval.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
