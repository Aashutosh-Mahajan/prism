# Module `viewer.src.ui`

<!-- prism:generated:facts -->
- Files: viewer/src/ui.ts
- Docstring: Tiny DOM helpers (no framework: the viewer must stay small and self-contained).
- Public API (by importance):
  - `$(id: string) -> T` (viewer/src/ui.ts:3)
  - `el(tag: K, props: Props = {}, children: Child[] = []) -> HTMLElementTagNameMap[K]` (viewer/src/ui.ts:12)
  - `toast(message: string, error = false)` (viewer/src/ui.ts:27)
  - `storage() -> Storage | null` (viewer/src/ui.ts:46)
  - `plural(n: number, word: string, many = `${word}s`) -> string` (viewer/src/ui.ts:70)
  - `stored(key: string) -> string | null` (viewer/src/ui.ts:54)
  - `announce(message: string)` — Polite announcement for screen readers (graph focus, results). (viewer/src/ui.ts:38)
  - `store(key: string, value: string)` (viewer/src/ui.ts:62)
  - `formatAgo(epochSeconds: number | null | undefined) -> string` (viewer/src/ui.ts:74)
- Used by: `viewer.src.app`, `viewer.src.chrome`, `viewer.src.controls`, `viewer.src.hovercard`, `viewer.src.inspector`, `viewer.src.layout`, `viewer.src.live`, `viewer.src.main`, `viewer.src.nodelist`, `viewer.src.search`, `viewer.src.theme`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
