# Module `prism.core`

<!-- prism:generated:facts -->
- Files: prism/core/__init__.py, prism/core/errors.py, prism/core/markers.py, prism/core/models.py, prism/core/paths.py, prism/core/tokens.py
- Docstring: Exceptions and the CLI exit codes they map to (CLAUDE.md Section 14).
- Public API (by importance):
  - `class UserError(PrismError)` (prism/core/errors.py:26)
  - `manifest_path(root: Path) -> Path` (prism/core/paths.py:16)
  - `aicontext_dir(root: Path) -> Path` (prism/core/paths.py:12)
  - `class Smell` — A cheap static lead for the audit plan. Not a finding. (prism/core/models.py:69)
  - `find_repo_root(start: Path) -> Path` — Nearest ancestor containing `.aicontext/`, else the git root, else `start`. (prism/core/paths.py:20)
  - `estimate_tokens(text: str) -> int` (prism/core/tokens.py:10)
  - `class IndexMissingError(PrismError)` (prism/core/errors.py:31)
  - `class Region` (prism/core/markers.py:26)
  - `parse_regions(text: str) -> dict[tuple[RegionKind, str], Region]` (prism/core/markers.py:47)
  - `class NotFoundError(UserError)` (prism/core/errors.py:41)
  - `class ImportRef` — One imported name. (prism/core/models.py:27)
  - `class EnvRead` — A configuration read with a literal key, e.g. `os.environ.get("DATABASE_URL")`. (prism/core/models.py:60)
  - … 28 more
- Used by: `prism`, `prism.audit`, `prism.discovery`, `prism.extractors`, `prism.graph`, `prism.health`, `prism.hooks`, `prism.incremental`, `prism.integrations`, `prism.mcp`, `prism.narrator`, `prism.navigator.api`, `prism.navigator.cache_db`, `prism.navigator.context_pack`, `prism.navigator.graphify`, `prism.navigator.resolve`, `prism.navigator.semantic`, `prism.navigator.session`, `prism.navigator.store`, `prism.navigator.task_pack`, `prism.parsing`, `prism.viewer.api`, `prism.viewer.model`, `prism.viewer.server`, `prism.writers`
- Tests: tests/benchmarks/tokens.py, tests/integration/test_audit.py, tests/integration/test_hooks_mcp.py, tests/integration/test_phase5.py, tests/integration/test_prompt_hook.py, tests/integration/test_refresh.py, tests/integration/test_scan.py, tests/integration/test_viewer.py, tests/unit/test_config.py, tests/unit/test_graph.py, tests/unit/test_navigator.py, tests/unit/test_python_parser.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py, tests/unit/test_task_retrieval.py, tests/unit/test_treesitter.py, tests/unit/test_writers.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
