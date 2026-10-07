# Module `prism.navigator.session`

<!-- prism:generated:facts -->
- Files: prism/navigator/session.py
- Docstring: Per-session memory of the code ranges already returned, so a repeat costs a reference line.
- Public API (by importance):
  - `load_seen(root: Path, session: str, manifest: dict[str, Any] | None = None) -> set[Range]` — Delivered ranges from unchanged source only; legacy caches are re-read once. (prism/navigator/session.py:49)
  - `save_seen(root: Path, session: str, seen: set[Range], manifest: dict[str, Any] | None = None) -> None` (prism/navigator/session.py:71)
  - `session_id(explicit: str | None) -> str | None` — The session to remember ranges in: an explicit id, else `PRISM_SESSION`. (prism/navigator/session.py:105)
- Depends on: `prism.core`, `prism.writers`
- Used by: `prism`, `prism.hooks`, `prism.mcp`
- Tests: tests/integration/test_prompt_hook.py, tests/unit/test_context_engine.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Persists delivered source ranges per session. load_seen invalidates ranges whose source revision changed; save_seen records only delivered evidence. Explicit IDs or PRISM_SESSION share memory across CLI, MCP and hooks.
<!-- /prism:narrative:summary -->
