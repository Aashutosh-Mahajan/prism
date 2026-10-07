# Module `prism.integrations`

<!-- prism:generated:facts -->
- Files: prism/integrations/__init__.py, prism/integrations/antigravity.py, prism/integrations/base.py, prism/integrations/claude_code.py, prism/integrations/codex.py, prism/integrations/common.py, prism/integrations/gemini.py, prism/integrations/git_hooks.py, prism/integrations/global_note.py, prism/integrations/hooks_json.py, prism/integrations/other_agents.py
- Docstring: Agent integrations. The core never imports these; `init`/`uninstall-integration` do.
- Public API (by importance):
  - `read_text(path: Path) -> str | None` (prism/integrations/base.py:89)
  - `get_integration(name: str) -> Integration` (prism/integrations/__init__.py:22)
  - `class IntegrationOptions` (prism/integrations/base.py:56)
  - `class FileChange` (prism/integrations/base.py:30)
  - `skill_text(name: str) -> str` (prism/integrations/common.py:41)
  - `all_removals(root: Path) -> list[FileChange]` (prism/integrations/__init__.py:48)
  - `class GitHooksIntegration(Integration)` (prism/integrations/git_hooks.py:46)
  - `strip_hooks(settings: dict[str, Any]) -> dict[str, Any]` — `settings` without any PRISM hook entry (empty events and an empty `hooks` are removed). (prism/integrations/hooks_json.py:30)
  - `detect_agents(root: Path) -> list[str]` (prism/integrations/__init__.py:38)
  - `all_integrations() -> list[Integration]` (prism/integrations/__init__.py:44)
  - `dump_json(data: dict[str, Any]) -> str` (prism/integrations/base.py:160)
  - `hooks_dir(root: Path) -> Path | None` (prism/integrations/git_hooks.py:28)
  - … 27 more
- Depends on: `prism.core`, `prism.writers`
- Used by: `prism`
- Tests: tests/benchmarks/agent_prepare.py, tests/benchmarks/agent_score.py, tests/benchmarks/edit_bench.py, tests/benchmarks/retrieval_eval.py, tests/benchmarks/run.py, tests/benchmarks/tokens.py, tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/integration/test_incremental.py, tests/integration/test_integrations.py, tests/integration/test_scan.py, tests/integration/test_update_paths.py, tests/integration/test_viewer.py, tests/unit/test_edit_bench.py, tests/unit/test_graphify_hints.py, tests/unit/test_task_pack.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
