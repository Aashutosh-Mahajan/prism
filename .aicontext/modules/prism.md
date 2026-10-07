# Module `prism`

<!-- prism:generated:facts -->
- Files: prism/__init__.py, prism/__main__.py, prism/cli.py, prism/config.py, prism/entry.py, prism/lifecycle.py, prism/maintenance.py, prism/pipeline.py, prism/status.py
- Docstring: PRISM: a persistent, local context layer for AI coding agents.
- Public API (by importance):
  - `run_index(root: Path, *, incremental: bool, files: list[str] | None = None, full: bool = False, lazy_rank: bool = True, lock_wait: float = 10.0) -> IndexRun` — Build (or incrementally update) the index and write `.aicontext/`. (prism/lifecycle.py:216)
  - `update(root: Path, files: list[str] | None = None, lazy_rank: bool = True, lock_wait: float = 10.0) -> IndexRun` (prism/lifecycle.py:338)
  - `scan(root: Path, full: bool = False, warm: bool = True) -> dict[str, Any]` — Build the whole index. By default the query caches are built too, so the first question (prism/lifecycle.py:327)
  - `plan_init(root: Path, agents: list[str] | tuple[str, ...] = (), options: IntegrationOptions | None = None, git_hooks: bool = False) -> InitPlan` — Plan every change `init` would make. Nothing is written. (prism/lifecycle.py:71)
  - `apply_init(plan: InitPlan) -> dict[str, Any]` (prism/lifecycle.py:110)
  - `build_index(root: Path, config: PrismConfig | None = None, known_files: dict[str, Any] | None = None, *, cached: dict[str, ParsedFile] | None = None, call_ranker: Ranker = pagerank, import_ranker: Ranker = pagerank, previous_git: GitIntel | None = None, files: list[SourceFile] | None = None) -> Index` (prism/pipeline.py:101)
  - `load_config(root: Path) -> PrismConfig` (prism/config.py:48)
  - `require_manifest(root: Path) -> dict[str, Any]` (prism/lifecycle.py:157)
  - `emit_json(data: Any) -> None` (prism/cli.py:67)
  - `class PrismConfig` (prism/config.py:23)
  - `emit(text: str) -> None` — Plain output: never interpreted as Rich markup. (prism/cli.py:62)
  - `compute_status(root: Path, check_files: bool = True) -> StatusReport` (prism/status.py:96)
  - … 56 more
- Depends on: `prism.audit`, `prism.consent`, `prism.core`, `prism.discovery`, `prism.drift`, `prism.extractors`, `prism.graph`, `prism.health`, `prism.hooks`, `prism.incremental`, `prism.integrations`, `prism.mcp`, `prism.narrator`, `prism.navigator.api`, `prism.navigator.freshness`, `prism.navigator.render`, `prism.navigator.session`, `prism.navigator.store`, `prism.navigator.task_pack`, `prism.parsing`, `prism.viewer.server`, `prism.writers`
- Used by: `prism.audit`, `prism.discovery`, `prism.extractors`, `prism.hooks`, `prism.incremental`, `prism.mcp`, `prism.navigator.api`, `prism.navigator.freshness`, `prism.navigator.graphify`, `prism.navigator.semantic`, `prism.navigator.store`, `prism.writers`
- External: click, jsonschema, rich, tomli, typer
- Tests: tests/benchmarks/agent_collect.py, tests/benchmarks/agent_prepare.py, tests/benchmarks/agent_score.py, tests/benchmarks/edit_bench.py, tests/benchmarks/retrieval_eval.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_audit.py, tests/integration/test_cli.py, tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/integration/test_incremental.py, tests/integration/test_integrations.py, tests/integration/test_phase5.py, tests/integration/test_prompt_hook.py, tests/integration/test_refresh.py, tests/integration/test_scan.py, tests/integration/test_update_paths.py, tests/integration/test_viewer.py, tests/skills/test_skill_templates.py, tests/unit/test_config.py, tests/unit/test_discovery.py, tests/unit/test_extractors.py, tests/unit/test_graphify_hints.py, tests/unit/test_navigator.py, tests/unit/test_phase3_extractors.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_task_retrieval.py, tests/unit/test_treesitter.py, tests/unit/test_writers.py
- Entry points: `prism.__main__`, `prism.entry.main`, `prism.cli.main`, `prism`, `prism.entry.main`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
