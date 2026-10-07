# Module `viewer.src.app`

<!-- prism:generated:facts -->
- Files: viewer/src/app.ts
- Docstring: The viewer's state and core operations. UI modules render from here; they never own state.
- Public API (by importance):
  - `emptyFilters() -> Filters` (viewer/src/app.ts:30)
  - `oneOf(value: string | null, allowed: readonly T[], fallback: T) -> T` (viewer/src/app.ts:60)
  - `class App` (viewer/src/app.ts:77)
  - `stateFromUrl(search: string) -> Partial<ViewState>` — URL parameters are untrusted input: accept only known values. (viewer/src/app.ts:65)
  - `interface ViewState` (viewer/src/app.ts:34)
- Depends on: `viewer.src.data`, `viewer.src.encode`, `viewer.src.inspector`, `viewer.src.layout`, `viewer.src.renderer`, `viewer.src.theme`, `viewer.src.types`, `viewer.src.ui`
- Used by: `viewer.src.chrome`, `viewer.src.controls`, `viewer.src.hovercard`, `viewer.src.inspector`, `viewer.src.layout`, `viewer.src.live`, `viewer.src.main`, `viewer.src.nodelist`, `viewer.src.renderer`, `viewer.src.search`
- External: graphology, graphology-communities-louvain, sigma, viewer
- Tests: tests/benchmarks/prism_mcp_client.mjs, tests/integration/test_phase5.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
