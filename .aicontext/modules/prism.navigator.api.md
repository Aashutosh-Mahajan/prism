# Module `prism.navigator.api`

<!-- prism:generated:facts -->
- Files: prism/navigator/api.py
- Docstring: Navigator operations as plain functions returning JSON-ready dicts.
- Public API (by importance):
  - `op_task(store: IndexStore, query: str, budget: int = 2000, seen: set[tuple[str, int, int]] | None = None, mode: str = 'auto') -> dict[str, Any]` — One-call retrieval for a request. `seen` (a session's already-returned code ranges) (prism/navigator/api.py:45)
  - `op_context(store: IndexStore, target: str, budget: int = DEFAULT_BUDGET, depth: int = 1, with_source: bool = False) -> dict[str, Any]` (prism/navigator/api.py:32)
  - `op_search(store: IndexStore, query: str, limit: int = 10, semantic: bool = False, embedder: Any = None) -> dict[str, Any]` (prism/navigator/api.py:68)
  - `op_brief(root: Path, full: bool = False) -> dict[str, Any]` (prism/navigator/api.py:168)
  - `op_impact(store: IndexStore, target: str, depth: int = DEFAULT_DEPTH) -> dict[str, Any]` (prism/navigator/api.py:61)
  - `op_module(store: IndexStore, name: str) -> dict[str, Any]` (prism/navigator/api.py:110)
  - `op_locate(store: IndexStore, name: str, limit: int = 10) -> dict[str, Any]` (prism/navigator/api.py:22)
  - `freshness_line(root: Path) -> str` (prism/navigator/api.py:140)
- Depends on: `prism`, `prism.core`, `prism.navigator.context_pack`, `prism.navigator.impact`, `prism.navigator.resolve`, `prism.navigator.semantic`, `prism.navigator.store`, `prism.navigator.task_pack`, `prism.writers`
- Used by: `prism`, `prism.hooks`, `prism.mcp`, `prism.viewer.api`
- Tests: tests/benchmarks/agent_prepare.py, tests/benchmarks/edit_bench.py, tests/benchmarks/retrieval_economics.py, tests/benchmarks/retrieval_eval.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_audit.py, tests/integration/test_phase5.py, tests/integration/test_prompt_hook.py, tests/unit/test_graphify_hints.py, tests/unit/test_navigator.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_task_retrieval.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
