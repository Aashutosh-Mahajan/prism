# Module `prism.navigator.support`

<!-- prism:generated:facts -->
- Files: prism/navigator/support.py
- Docstring: Source-verified local definitions needed to interpret a retrieved Python body.
- Public API (by importance):
  - `produces_shape(source: str, fields: set[str]) -> bool` — Verify a Python dictionary is returned, directly or through its container. (prism/navigator/support.py:15)
  - `class SupportRange` (prism/navigator/support.py:76)
  - `local_support(reader: SourceReader, file: str, ranges: list[tuple[int, int]]) -> list[SupportRange]` — Resolve loaded names to top-level constants/imports/helpers, not whole headers. (prism/navigator/support.py:84)
- Depends on: `prism.navigator.source_index`
- Used by: `prism.navigator.task_pack`
- Tests: tests/unit/test_context_engine.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Resolves local Python constants, imports and helpers needed by retrieved code. produces_shape checks AST return evidence for requested dictionary fields, excluding unrelated nested bodies and logging-only dictionaries.
<!-- /prism:narrative:summary -->
