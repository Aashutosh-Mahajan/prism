# Module `prism.navigator.cache_db`

<!-- prism:generated:facts -->
- Files: prism/navigator/cache_db.py
- Docstring: SQLite query cache in `.aicontext/cache/`, rebuilt from the JSON artifacts.
- Public API (by importance):
  - `open_cache(root: Path, manifest: dict[str, Any]) -> sqlite3.Connection` — Open (building if needed) the cache for the current artifacts. (prism/navigator/cache_db.py:97)
  - `fingerprint(manifest: dict[str, Any]) -> str` (prism/navigator/cache_db.py:81)
  - `cache_dir(root: Path) -> Path` (prism/navigator/cache_db.py:90)
- Depends on: `prism.core`, `prism.navigator.text`
- Used by: `prism.navigator.freshness`, `prism.navigator.semantic`, `prism.navigator.source_index`, `prism.navigator.store`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
