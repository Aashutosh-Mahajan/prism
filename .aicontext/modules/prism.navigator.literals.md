# Module `prism.navigator.literals`

<!-- prism:generated:facts -->
- Files: prism/navigator/literals.py
- Docstring: Evidence evidence: exact strings, identifiers and quantities named in a request.
- Public API (by importance):
  - `class Evidence` (prism/navigator/literals.py:64)
  - `looks_like_code(word: str) -> bool` (prism/navigator/literals.py:120)
  - `class Occurrence` (prism/navigator/literals.py:45)
  - `find_literals(index: SourceIndex, reader: SourceReader, query: str, per_literal: int = 8, context_fields: set[str] | None = None) -> EvidenceResult` — Everything in the request that can be matched exactly, and where it occurs. (prism/navigator/literals.py:272)
  - `class EvidenceResult` (prism/navigator/literals.py:99)
- Depends on: `prism.navigator.source_index`, `prism.navigator.text`
- Used by: `prism.navigator.task_pack`
- Tests: tests/unit/test_context_engine.py, tests/unit/test_task_disclosure.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Finds exact quoted text, identifiers, quantities and phrases through source postings. Reports exhaustive versus limited evidence explicitly. Backtick references to fields in a requested output extension are contextual; literal strings and ordinary rename targets retain exact matching.
<!-- /prism:narrative:summary -->
