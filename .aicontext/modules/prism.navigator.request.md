# Module `prism.navigator.request`

<!-- prism:generated:facts -->
- Files: prism/navigator/request.py
- Docstring: Separate an edit's leading operation from its acceptance criteria.
- Public API (by importance):
  - `request_focus(query: str) -> str` — Prefer the requested change over lengthy examples and rejection rules. (prism/navigator/request.py:38)
  - `request_operations(query: str) -> set[str]` — Name-level operation evidence, independent of later error examples. (prism/navigator/request.py:26)
- Depends on: `prism.navigator.text`
- Used by: `prism.navigator.task_pack`
- Tests: tests/unit/test_context_engine.py, tests/unit/test_request_ranking.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Separates a leading requested edit from later acceptance criteria for ranking. request_focus handles imperative and noun-first modal requests; request_operations provides operation-name evidence.
<!-- /prism:narrative:summary -->
