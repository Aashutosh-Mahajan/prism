# Module `prism.navigator.freshness`

<!-- prism:generated:facts -->
- Files: prism/navigator/freshness.py
- Docstring: Answer from the current working tree, not from whenever the index was last updated.
- Public API (by importance):
  - `warm_caches(root: Path) -> None` — Build the query caches (symbol database and source postings) now, so the first question (prism/navigator/freshness.py:39)
  - `refresh_if_stale(root: Path, max_files: int = MAX_FILES, wait: float = LOCK_WAIT_SECONDS) -> int` — Update the index for files changed since the last update. Returns how many changed. (prism/navigator/freshness.py:55)
  - `caches_ready(root: Path) -> bool` — True when a query would not have to build the symbol database or the source postings (prism/navigator/freshness.py:25)
- Depends on: `prism`, `prism.consent`, `prism.incremental`, `prism.navigator.cache_db`, `prism.navigator.source_index`, `prism.navigator.store`, `prism.writers`
- Used by: `prism`, `prism.hooks`, `prism.mcp`
- Tests: tests/integration/test_freshness.py, tests/integration/test_prompt_hook.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
