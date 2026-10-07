# Module `viewer.src.renderer`

<!-- prism:generated:facts -->
- Files: viewer/src/renderer.ts
- Docstring: Sigma (WebGL) renderer: node/edge programs, labels, and the reducers that turn view state
- Public API (by importance):
  - `createRenderer(app: App, container: HTMLElement) -> Sigma` (viewer/src/renderer.ts:63)
  - `bindDragging(app: App, renderer: Sigma)` — Drag to move a node; the node stays pinned where it is dropped. (viewer/src/renderer.ts:176)
  - `drawHighlight(ctx: Ctx, d: Drawn)` (viewer/src/renderer.ts:32)
  - `drawLabel(ctx: Ctx, d: Drawn, weight = 400)` (viewer/src/renderer.ts:20)
  - `class Animator` — Pulses animate every frame for a moment; the activity trail only needs a redraw when it (viewer/src/renderer.ts:205)
  - `interface Drawn` (viewer/src/renderer.ts:18)
- Depends on: `viewer.src.app`, `viewer.src.theme`
- Used by: `viewer.src.app`, `viewer.src.controls`, `viewer.src.live`, `viewer.src.main`
- External: @sigma, sigma, viewer
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
