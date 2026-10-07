# Module `prism.navigator.overview`

<!-- prism:generated:facts -->
- Files: prism/navigator/overview.py
- Docstring: Query-focused repository maps: signatures and relationships, never source dumps.
- Public API (by importance):
  - `render_overview(overview: dict[str, Any]) -> list[str]` (prism/navigator/overview.py:197)
  - `overview_items(store: IndexStore, reader: SourceReader, query: str) -> dict[str, Any]` — Return bounded candidates; the task assembler fits every row to its budget. (prism/navigator/overview.py:56)
  - `wants_overview(query: str) -> bool` (prism/navigator/overview.py:52)
- Depends on: `prism.navigator.source_index`, `prism.navigator.store`, `prism.navigator.text`
- Used by: `prism.navigator.task_pack`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Builds query-focused maps of symbol signatures and relationships. These maps locate code without dumping bodies. task_pack fits the returned candidates into the requested budget.
<!-- /prism:narrative:summary -->
