# Module `viewer.src.data`

<!-- prism:generated:facts -->
- Files: viewer/src/data.ts
- Docstring: Data sources: the local PRISM server (`prism view`) or data embedded by `prism graph export --html`.
- Public API (by importance):
  - `class ApiError extends Error` (viewer/src/data.ts:32)
  - `getJson(url: string) -> Promise<T>` (viewer/src/data.ts:53)
  - `request(url: string, init: RequestInit) -> Promise<Response>` — fetch() rejects with a bare "Failed to fetch" TypeError when the server is gone; say what happened instead. (viewer/src/data.ts:42)
  - `postJson(url: string, body: unknown) -> Promise<void>` (viewer/src/data.ts:65)
  - `neighbourhood(edges: GEdge[], root: string, depth: number, directed = false) -> Map<string, number>` (viewer/src/data.ts:151)
  - `class HttpSource implements DataSource` (viewer/src/data.ts:88)
  - `class StaticSource implements DataSource` (viewer/src/data.ts:178)
  - `queryString(q: GraphQuery) -> string` (viewer/src/data.ts:74)
  - `globToRegExp(glob: string) -> RegExp` (viewer/src/data.ts:173)
  - `createSource() -> DataSource` (viewer/src/data.ts:339)
  - `interface DataSource` (viewer/src/data.ts:16)
  - `interface StaticBundle` (viewer/src/data.ts:139)
- Depends on: `viewer.src.types`
- Used by: `viewer.src.app`, `viewer.src.live`, `viewer.src.main`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
