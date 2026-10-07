# Module `prism.navigator.api`

<!-- prism:generated:facts -->
- Files: prism/navigator/api.py
- Docstring: Navigator operations as plain functions returning JSON-ready dicts.
- Public API (by importance):
  - `op_task(store: IndexStore, query: str, budget: int = 2000, seen: set[tuple[str, int, int]] | None = None, mode: str = 'auto') -> dict[str, Any]` — One-call retrieval for a request. `seen` (a session's already-returned code ranges) (prism/navigator/api.py:45)
  - `op_context(store: IndexStore, target: str, budget: int = DEFAULT_BUDGET, depth: int = 1, with_source: bool = False) -> dict[str, Any]` (prism/navigator/api.py:32)
  - `op_search(store: IndexStore, query: str, limit: int = 10, semantic: bool = False, embedder: Any = None) -> dict[str, Any]` (prism/navigator/api.py:94)
  - `op_brief(root: Path, full: bool = False) -> dict[str, Any]` (prism/navigator/api.py:194)
  - `op_impact(store: IndexStore, target: str, depth: int = DEFAULT_DEPTH) -> dict[str, Any]` (prism/navigator/api.py:87)
  - `op_module(store: IndexStore, name: str) -> dict[str, Any]` (prism/navigator/api.py:136)
  - `op_locate(store: IndexStore, name: str, limit: int = 10) -> dict[str, Any]` (prism/navigator/api.py:22)
  - `freshness_line(root: Path) -> str` (prism/navigator/api.py:166)
  - `op_knowledge(store: IndexStore, budget: int = 600) -> dict[str, Any]` — Inspect what is indexed locally without injecting the entire project. (prism/navigator/api.py:80)
- Depends on: `prism`, `prism.core`, `prism.navigator.context_pack`, `prism.navigator.impact`, `prism.navigator.knowledge`, `prism.navigator.resolve`, `prism.navigator.semantic`, `prism.navigator.store`, `prism.navigator.task_pack`, `prism.writers`
- Used by: `prism`, `prism.hooks`, `prism.mcp`, `prism.viewer.api`
- Tests: tests/benchmarks/agent_prepare.py, tests/benchmarks/edit_bench.py, tests/benchmarks/retrieval_economics.py, tests/benchmarks/retrieval_eval.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_audit.py, tests/integration/test_phase5.py, tests/integration/test_prompt_hook.py, tests/unit/test_context_engine.py, tests/unit/test_graphify_hints.py, tests/unit/test_navigator.py, tests/unit/test_request_ranking.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_task_retrieval.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Plain functions returning JSON-ready results for CLI and MCP. op_task assembles or reuses revision-guarded task packets; op_knowledge returns a bounded inventory. Keep transport behavior in adapters and retrieval behavior in navigator.
<!-- /prism:narrative:summary -->
