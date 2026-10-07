# Module `prism.mcp`

<!-- prism:generated:facts -->
- Files: prism/mcp/__init__.py, prism/mcp/server.py
- Docstring: `prism mcp`: stdio MCP server exposing the navigator (and audit/refresh) as tools.
- Public API (by importance):
  - `build_server(root: Path, profile: str | None = None) -> Any` (prism/mcp/server.py:262)
  - `class PrismTools` — Tool implementations bound to one repo, keeping the index open between calls. (prism/mcp/server.py:36)
  - `enabled_tools(root: Path, profile: str | None = None) -> list[str]` (prism/mcp/server.py:244)
  - `resolve_profile(profile: str | None = None) -> str` — `lean` unless `full` is asked for (argument, else PRISM_MCP_PROFILE). (prism/mcp/server.py:238)
  - `run(root: Path, profile: str | None = None) -> None` (prism/mcp/server.py:274)
- Depends on: `prism`, `prism.audit`, `prism.consent`, `prism.core`, `prism.narrator`, `prism.navigator.api`, `prism.navigator.freshness`, `prism.navigator.store`, `prism.viewer.server`, `prism.writers`
- Used by: `prism`
- Tests: tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/skills/test_skill_templates.py, tests/unit/test_task_pack.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
