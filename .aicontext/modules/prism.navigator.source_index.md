# Module `prism.navigator.source_index`

<!-- prism:generated:facts -->
- Files: prism/navigator/source_index.py
- Docstring: Persistent body search. Synchronize changed manifest hashes, never rescan on a query.
- Public API (by importance):
  - `class SourceIndex` — A synchronized read view of the persistent source postings (use as a context manager). (prism/navigator/source_index.py:66)
  - `read_indexed_source(store: IndexStore, file: str) -> str | None` — Only expose source matching the indexed revision and inside this repository. (prism/navigator/source_index.py:26)
  - `split_lines(text: str) -> list[str]` — Lines numbered the way the parsers number them (`\n`), without a phantom last line. (prism/navigator/source_index.py:41)
  - `class SourceReader` — Verified source lines for one request, read at most once per file. (prism/navigator/source_index.py:49)
  - `search_sources(store: IndexStore, query: str, limit: int = 10) -> list[tuple[str, float]]` — BM25 over source bodies and paths, with changed-file-only cache maintenance. (prism/navigator/source_index.py:228)
  - `pending_files(root: Path, manifest: dict[str, Any]) -> int` — How many indexed files the persistent source postings do not yet reflect. Read-only: it (prism/navigator/source_index.py:209)
- Depends on: `prism.navigator.cache_db`, `prism.navigator.store`, `prism.navigator.text`, `viewer.src.types`
- Used by: `prism.navigator.context_pack`, `prism.navigator.freshness`, `prism.navigator.graphify`, `prism.navigator.literals`, `prism.navigator.overview`, `prism.navigator.support`, `prism.navigator.task_pack`
- Tests: tests/unit/test_graphify_hints.py, tests/unit/test_task_disclosure.py, tests/unit/test_task_pack.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
