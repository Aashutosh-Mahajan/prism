# Module `viewer.src.encode`

<!-- prism:generated:facts -->
- Files: viewer/src/encode.ts
- Docstring: Visual encodings: node colour, size, and shape from node attributes, plus legends.
- Public API (by importance):
  - `max(values: number[], floor: number) -> number` (viewer/src/encode.ts:120)
  - `paletteColor(i: number) -> string` (viewer/src/encode.ts:55)
  - `nodeColor(n: GNode, by: ColorBy, ctx: EncodeContext) -> string` (viewer/src/encode.ts:151)
  - `buildContext(nodes: GNode[], community: Map<string, number>) -> EncodeContext` (viewer/src/encode.ts:126)
  - `nodeSize(n: GNode, by: SizeBy, ctx: EncodeContext) -> number` (viewer/src/encode.ts:186)
  - `nodeType(n: GNode) -> "square" | "border" | "circle"` — Shape encodes what a node *is*: squares hold code, rings group or check it, dots are callables. (viewer/src/encode.ts:191)
  - `ramp(stops: [number, number, number][], t: number) -> string` (viewer/src/encode.ts:91)
  - `sizeValue(n: GNode, by: SizeBy, ctx: EncodeContext) -> number` (viewer/src/encode.ts:179)
  - `lerp(a: number, b: number, t: number) -> number` (viewer/src/encode.ts:87)
  - `hash(text: string) -> number` (viewer/src/encode.ts:49)
  - `categoricalScale(keys: Iterable<string>, counts?: Map<string, number>) -> Map<string, string>` — Stable colours for a set of categories: sorted by size so the biggest groups get the (viewer/src/encode.ts:65)
  - `kindColor(kind: string) -> string` (viewer/src/encode.ts:103)
  - … 7 more
- Depends on: `viewer.src.types`
- Used by: `viewer.src.app`, `viewer.src.chrome`, `viewer.src.controls`, `viewer.src.search`, `viewer.src.theme`, `viewer.src.views`
- Tests: viewer/tests/graph.test.mjs
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
