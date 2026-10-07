# Module `prism.navigator.session`

<!-- prism:generated:facts -->
- Files: prism/navigator/session.py
- Docstring: Per-session memory of the code ranges already returned, so a repeat costs a reference line.
- Public API (by importance):
  - `load_seen(root: Path, session: str, manifest: dict[str, Any] | None = None) -> set[Range]` — Delivered ranges from unchanged source only; legacy caches are re-read once. (prism/navigator/session.py:49)
  - `save_seen(root: Path, session: str, seen: set[Range], manifest: dict[str, Any] | None = None) -> None` (prism/navigator/session.py:71)
  - `session_id(explicit: str | None) -> str | None` — The session to remember ranges in: an explicit id, else `PRISM_SESSION`. (prism/navigator/session.py:105)
- Depends on: `prism.core`, `prism.writers`
- Used by: `prism`, `prism.hooks`
- Tests: tests/integration/test_prompt_hook.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
