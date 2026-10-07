# Module `viewer.src.inspector`

<!-- prism:generated:facts -->
- Files: viewer/src/inspector.ts
- Docstring: Node inspector. Renders immediately from what the graph already knows (identity, metrics,
- Public API (by importance):
  - `stat(label: string, value: string | number, small?: string) -> HTMLElement` (viewer/src/inspector.ts:77)
  - `shortName(ref: string) -> string` (viewer/src/inspector.ts:25)
  - `renderInspector(app: App, id: string, focusPanel: boolean)` (viewer/src/inspector.ts:240)
  - `linkList(app: App, items: LinkItem[]) -> HTMLElement` (viewer/src/inspector.ts:32)
  - `section(title: string, count: number | null, body: Node, open = true) -> HTMLDetailsElement` (viewer/src/inspector.ts:70)
  - `copy(text: string) -> Promise<void>` (viewer/src/inspector.ts:88)
  - `editorLink(editor: { path: string; line: number }) -> string` (viewer/src/inspector.ts:81)
  - `actions(app: App, id: string, n: GNode | null, d: Details | null) -> HTMLElement` (viewer/src/inspector.ts:136)
  - `enrich(app: App, n: GNode | null, d: Details, body: HTMLElement, shown: Set<string>)` (viewer/src/inspector.ts:172)
  - `header(app: App, id: string, n: GNode | null, body: HTMLElement)` (viewer/src/inspector.ts:97)
  - `inView(app: App, id: string, body: HTMLElement) -> Set<string>` (viewer/src/inspector.ts:152)
  - `interface LinkItem` (viewer/src/inspector.ts:19)
- Depends on: `viewer.src.app`, `viewer.src.types`, `viewer.src.ui`
- Used by: `viewer.src.app`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
