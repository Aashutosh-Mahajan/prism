# Module `prism.writers`

<!-- prism:generated:facts -->
- Files: prism/writers/__init__.py, prism/writers/activity.py, prism/writers/agents_md.py, prism/writers/artifacts.py, prism/writers/decisions.py, prism/writers/graph_export.py, prism/writers/index_writer.py, prism/writers/json_writer.py, prism/writers/manifest.py, prism/writers/modules_md.py, prism/writers/narrative.py, prism/writers/obsidian.py, prism/writers/task_cache.py
- Docstring: The only package that writes into `.aicontext/`.
- Public API (by importance):
  - `write_text(path: Path, text: str) -> bool` — Write `text` with LF newlines. Returns False if the file already had this content. (prism/writers/json_writer.py:34)
  - `load_manifest(root: Path) -> dict[str, Any] | None` (prism/writers/manifest.py:24)
  - `read_json(path: Path) -> Any` (prism/writers/json_writer.py:58)
  - `record_activity(root: Path, op: str, ids: Iterable[str]) -> None` (prism/writers/activity.py:24)
  - `write_json(path: Path, data: Any) -> bool` (prism/writers/json_writer.py:54)
  - `dumps(data: Any) -> str` (prism/writers/json_writer.py:30)
  - `now_iso() -> str` (prism/writers/manifest.py:20)
  - `write_manifest(root: Path, manifest: dict[str, Any]) -> None` (prism/writers/manifest.py:46)
  - `load_packet(path: Path) -> dict[str, Any] | None` (prism/writers/task_cache.py:47)
  - `packet_current(root: Path, manifest: dict[str, Any], packet: dict[str, Any]) -> bool` — Never return cached code solely on a timestamp check: verify delivered files. (prism/writers/task_cache.py:57)
  - `packet_path(root: Path, stamp: str, query: str, budget: int, mode: str) -> Path` (prism/writers/task_cache.py:41)
  - `save_packet(path: Path, packet: dict[str, Any]) -> None` (prism/writers/task_cache.py:77)
  - … 44 more
- Depends on: `prism`, `prism.core`, `prism.drift`, `prism.viewer.model`
- Used by: `prism`, `prism.audit`, `prism.consent`, `prism.hooks`, `prism.integrations`, `prism.mcp`, `prism.narrator`, `prism.navigator.api`, `prism.navigator.freshness`, `prism.navigator.session`, `prism.navigator.store`, `prism.viewer.api`, `prism.viewer.model`, `prism.viewer.server`
- Tests: tests/benchmarks/agent_report.py, tests/benchmarks/edit_bench.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/integration/test_incremental.py, tests/integration/test_integrations.py, tests/integration/test_phase5.py, tests/integration/test_prompt_hook.py, tests/integration/test_scan.py, tests/integration/test_update_paths.py, tests/integration/test_viewer.py, tests/test_agent_measure.py, tests/unit/test_context_engine.py, tests/unit/test_discovery.py, tests/unit/test_edit_bench.py, tests/unit/test_graphify_hints.py, tests/unit/test_navigator.py, tests/unit/test_phase3_extractors.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_writers.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Owns persisted .aicontext artifacts, manifests, narratives and caches. task_cache writes bounded packets atomically and verifies delivered source before reuse. Cache reuse saves computation; model-token savings require compact delivery and fewer retrieval turns.
<!-- /prism:narrative:summary -->
