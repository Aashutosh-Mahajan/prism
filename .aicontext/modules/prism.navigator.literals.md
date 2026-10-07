# Module `prism.navigator.literals`

<!-- prism:generated:facts -->
- Files: prism/navigator/literals.py
- Docstring: Evidence evidence: exact strings, identifiers and quantities named in a request.
- Public API (by importance):
  - `class Evidence` (prism/navigator/literals.py:64)
  - `looks_like_code(word: str) -> bool` (prism/navigator/literals.py:120)
  - `find_literals(index: SourceIndex, reader: SourceReader, query: str, per_literal: int = 8) -> EvidenceResult` — Everything in the request that can be matched exactly, and where it occurs. (prism/navigator/literals.py:270)
  - `class Occurrence` (prism/navigator/literals.py:45)
  - `class EvidenceResult` (prism/navigator/literals.py:99)
- Depends on: `prism.navigator.source_index`, `prism.navigator.text`
- Used by: `prism.navigator.task_pack`
- Tests: tests/unit/test_task_disclosure.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
