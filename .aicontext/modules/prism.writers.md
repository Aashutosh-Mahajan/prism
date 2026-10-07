# Module `prism.writers`

<!-- prism:generated:facts -->
- Files: prism/writers/__init__.py, prism/writers/activity.py, prism/writers/agents_md.py, prism/writers/artifacts.py, prism/writers/decisions.py, prism/writers/graph_export.py, prism/writers/index_writer.py, prism/writers/json_writer.py, prism/writers/manifest.py, prism/writers/modules_md.py, prism/writers/narrative.py, prism/writers/obsidian.py
- Docstring: The only package that writes into `.aicontext/`.
- Public API (by importance):
  - `write_text(path: Path, text: str) -> bool` — Write `text` with LF newlines. Returns False if the file already had this content. (prism/writers/json_writer.py:34)
  - `load_manifest(root: Path) -> dict[str, Any] | None` (prism/writers/manifest.py:24)
  - `record_activity(root: Path, op: str, ids: Iterable[str]) -> None` (prism/writers/activity.py:24)
  - `read_json(path: Path) -> Any` (prism/writers/json_writer.py:58)
  - `write_json(path: Path, data: Any) -> bool` (prism/writers/json_writer.py:54)
  - `dumps(data: Any) -> str` (prism/writers/json_writer.py:30)
  - `now_iso() -> str` (prism/writers/manifest.py:20)
  - `activity_path(root: Path) -> Path` (prism/writers/activity.py:20)
  - `write_manifest(root: Path, manifest: dict[str, Any]) -> None` (prism/writers/manifest.py:46)
  - `list_decisions(root: Path) -> list[dict[str, Any]]` (prism/writers/decisions.py:52)
  - `written_narrative(text: str) -> dict[str, str]` — Narrative sections a human or agent has actually written (placeholders do not count). (prism/writers/agents_md.py:106)
  - `decisions_dir(root: Path) -> Path` (prism/writers/decisions.py:26)
  - … 39 more
- Depends on: `prism`, `prism.core`, `prism.drift`, `prism.viewer.model`
- Used by: `prism`, `prism.audit`, `prism.consent`, `prism.hooks`, `prism.integrations`, `prism.mcp`, `prism.narrator`, `prism.navigator.api`, `prism.navigator.freshness`, `prism.navigator.session`, `prism.navigator.store`, `prism.viewer.api`, `prism.viewer.model`, `prism.viewer.server`
- Tests: tests/benchmarks/agent_report.py, tests/benchmarks/edit_bench.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/integration/test_incremental.py, tests/integration/test_integrations.py, tests/integration/test_phase5.py, tests/integration/test_scan.py, tests/integration/test_update_paths.py, tests/integration/test_viewer.py, tests/test_agent_measure.py, tests/unit/test_discovery.py, tests/unit/test_edit_bench.py, tests/unit/test_graphify_hints.py, tests/unit/test_navigator.py, tests/unit/test_phase3_extractors.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_writers.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
