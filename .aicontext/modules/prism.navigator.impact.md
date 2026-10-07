# Module `prism.navigator.impact`

<!-- prism:generated:facts -->
- Files: prism/navigator/impact.py
- Docstring: `prism impact`: what could break if a target changes, and which tests to run.
- Public API (by importance):
  - `impact(store: IndexStore, target: Target, depth: int = DEFAULT_DEPTH) -> dict[str, Any]` (prism/navigator/impact.py:54)
  - `dependents(store: IndexStore, target: Target, depth: int = DEFAULT_DEPTH) -> dict[str, Any]` — Symbol- and file-level dependents by distance (the raw data behind `impact`). (prism/navigator/impact.py:30)
- Depends on: `prism.graph`, `prism.navigator.resolve`, `prism.navigator.store`
- Used by: `prism.navigator.api`, `prism.navigator.context_pack`, `prism.navigator.task_pack`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
