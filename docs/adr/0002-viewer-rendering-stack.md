# ADR 0002 — Graph viewer rendering stack

Status: accepted · 2026-09-27

## Context

CLAUDE.md §11 asks for an Obsidian-style graph viewer that stays smooth (≥ 30 fps, target 60)
with 5,000 visible nodes, paints the module-level graph in under 2 s on a 100k-line repository,
works fully offline, and needs no Node.js for end users. It asks for the rendering choice to be
recorded as an ADR.

## Decision

- **Rendering:** Sigma.js 3 (WebGL) over a Graphology graph, with `@sigma/node-square` and
  `@sigma/node-border` for node shapes that encode kind.
- **Layout:** ForceAtlas2 from `graphology-layout-forceatlas2`, run in its Web Worker for a
  bounded time, starting from a deterministic, package-grouped seed layout. Barnes–Hut is enabled
  above 300 nodes.
- **Communities:** Louvain from `graphology-communities-louvain`, computed on demand for the
  *Community* colouring.
- **Frontend:** TypeScript with no UI framework, built by Vite into one JS and one CSS file in
  `prism/viewer_dist/`, shipped as Python package data.
- **Fonts and assets:** JetBrains Mono from `@fontsource`, inlined into the CSS; no CDN and no
  runtime requests except the viewer's own `/api` on `127.0.0.1`.
- **Backend:** Python standard library only (`http.server` with Server-Sent Events).

## Alternatives considered

| Option | Why not |
|---|---|
| Cytoscape.js | Richer built-in layouts, but canvas rendering slows down well before 5,000 nodes |
| `force-graph` / `3d-force-graph` | Attractive, but weaker at large 2D graphs and label management; kept in mind for an optional 3D mode |
| D3 with SVG | Flexible, but SVG cannot hold thousands of nodes at interactive frame rates |
| A UI framework (React, Svelte) | Adds bundle size and build complexity for a handful of panels; plain DOM modules are enough |
| FastAPI / uvicorn backend | Extra runtime dependencies for a local, single-user server |

## Consequences

- Handles thousands of nodes at interactive frame rates; measured about 14 ms p50 and 18 ms p95
  per frame while laying out a 4,020-node symbol graph.
- Hovering and focus are implemented in Sigma's node and edge reducers, so highlight changes
  refresh without rebuilding the graph.
- Graph accessibility needs deliberate work because WebGL has no DOM: keyboard spatial
  navigation, screen-reader announcements and a parallel ARIA listbox of nodes provide it.
- Contributors need Node 24 to change the frontend; users never do. CI rebuilds the bundle and
  fails if the committed `viewer_dist` differs.
