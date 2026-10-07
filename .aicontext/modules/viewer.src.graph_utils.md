# Module `viewer.src.graph_utils`

<!-- prism:generated:facts -->
- Files: viewer/src/graph-utils.ts
- Docstring: Pure graph helpers (no DOM): adjacency, path edges, request generations, seed layout,
- Public API (by importance):
  - `edgeKey(source: string, target: string) -> string` (viewer/src/graph-utils.ts:33)
  - `hash01(text: string) -> number` (viewer/src/graph-utils.ts:57)
  - `interface Relations` (viewer/src/graph-utils.ts:17)
  - `class RequestGeneration` — A generation also invalidates in-flight work when an input is cleared. (viewer/src/graph-utils.ts:47)
  - `adjacency(edges: Pick<GEdge, "source" | "target">[]) -> Map<string, Set<string>>` — Build once per payload instead of scanning every edge for each new node. (viewer/src/graph-utils.ts:6)
  - `nearestInDirection( from: { x: number; y: number }, candidates: Iterable<[string, { x: number; y: number }]>, direction: Direction, ) -> string | null` — Keyboard graph navigation: the best node in a direction, preferring close nodes that lie (viewer/src/graph-utils.ts:102)
  - `pathEdges(nodes: string[], directed: boolean) -> Set<string>` (viewer/src/graph-utils.ts:37)
  - `percentile(values: number[], value: number) -> number` — Percentile rank (0–100) of `value` within `values`. (viewer/src/graph-utils.ts:125)
  - `relations(edges: Pick<GEdge, "source" | "target">[]) -> Relations` — Directed neighbour lists, for the inspector's "in this view" connections. (viewer/src/graph-utils.ts:23)
  - `seedPositions(nodes: Pick<GNode, "id" | "group" | "rank">[], spacing = 1) -> Map<string, { x: number; y: number }>` — Deterministic structured starting positions: each group becomes a sunflower (phyllotaxis) (viewer/src/graph-utils.ts:71)
- Depends on: `viewer.src.types`
- Tests: viewer/tests/graph.test.mjs
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
