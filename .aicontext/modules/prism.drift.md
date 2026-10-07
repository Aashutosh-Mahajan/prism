# Module `prism.drift`

<!-- prism:generated:facts -->
- Files: prism/drift/__init__.py, prism/drift/scoring.py, prism/drift/structural_diff.py
- Docstring: Accumulate drift per narrative section and mark sections stale (CLAUDE.md 9.2).
- Public API (by importance):
  - `snapshot(docs: dict[str, dict[str, Any]]) -> dict[str, Any]` (prism/drift/structural_diff.py:33)
  - `diff(old: dict[str, Any], new: dict[str, Any]) -> list[Change]` (prism/drift/structural_diff.py:71)
  - `reset_section(drift: dict[str, Any], name: str, when: str) -> dict[str, Any]` (prism/drift/scoring.py:40)
  - `class Change` (prism/drift/structural_diff.py:17)
  - `apply_drift(drift: dict[str, Any], changes: list[Change], threshold: int, sections_present: set[str]) -> dict[str, Any]` — Return an updated `manifest["drift"]`. Only sections that exist are tracked. (prism/drift/scoring.py:13)
- Used by: `prism`, `prism.narrator`, `prism.writers`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
