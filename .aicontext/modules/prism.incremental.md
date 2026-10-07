# Module `prism.incremental`

<!-- prism:generated:facts -->
- Files: prism/incremental/__init__.py, prism/incremental/hash_cache.py, prism/incremental/lock.py
- Docstring: Parse cache and incremental state in `.aicontext/cache/state.sqlite` (gitignored).
- Public API (by importance):
  - `class UpdateLock` (prism/incremental/lock.py:29)
  - `class LockBusy(RuntimeError)` — Another process holds the update lock and did not release it within the wait. (prism/incremental/lock.py:25)
  - `class StateCache` (prism/incremental/hash_cache.py:58)
- Depends on: `prism`, `prism.core`, `viewer.src.types`
- Used by: `prism`, `prism.hooks`, `prism.navigator.freshness`
- Tests: tests/benchmarks/agent_collect.py, tests/benchmarks/agent_measure.py, tests/benchmarks/agent_report.py, tests/benchmarks/agent_score.py, tests/benchmarks/edit_bench.py, tests/benchmarks/prism_mcp_client.mjs, tests/benchmarks/retrieval_economics.py, tests/benchmarks/retrieval_eval.py, tests/benchmarks/tokens.py, tests/integration/test_freshness.py, tests/integration/test_integrations.py, tests/integration/test_viewer.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_retrieval.py, viewer/tests/graph.test.mjs
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
