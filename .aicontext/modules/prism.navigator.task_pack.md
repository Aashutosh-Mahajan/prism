# Module `prism.navigator.task_pack`

<!-- prism:generated:facts -->
- Files: prism/navigator/task_pack.py
- Docstring: One-call task retrieval: exact literals, verified code, callers, tests and impact.
- Public API (by importance):
  - `render_task(pack: dict[str, Any]) -> str` (prism/navigator/task_pack.py:105)
  - `build_task(store: IndexStore, query: str, budget: int = 2000, seen: set[tuple[str, int, int]] | None = None, mode: str = 'auto') -> dict[str, Any]` (prism/navigator/task_pack.py:314)
- Depends on: `prism._vendor`, `prism.core`, `prism.navigator.fusion`, `prism.navigator.graphify`, `prism.navigator.impact`, `prism.navigator.literals`, `prism.navigator.overview`, `prism.navigator.request`, `prism.navigator.resolve`, `prism.navigator.source_index`, `prism.navigator.store`, `prism.navigator.support`, `prism.navigator.synonyms`, `prism.navigator.text`
- Used by: `prism`, `prism.hooks`, `prism.mcp`, `prism.navigator.api`
- Tests: tests/unit/test_context_engine.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_task_retrieval.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Compiles one request into budgeted source, literal evidence, contracts, construction candidates, callers and tests. Verified Python output producers and exact scalar settings receive priority. Partial packets retain recovery ranges. Construction detection is bounded static evidence; normal validation still covers dynamic cases.
<!-- /prism:narrative:summary -->
