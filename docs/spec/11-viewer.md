## 11. Visualizer — Interactive Code Graph (Obsidian-style)

### 11.1 Concept

The index is a graph, and people should be able to **see** it the way Obsidian, Logseq, or Neo4j Bloom show a knowledge graph: a living, zoomable, force-directed web where every node is a module, file, class, or function and every link is an import, call, test relation, or co-change. This is how a human understands the codebase at a glance, checks what the agent is about to touch, and spots tangles, hubs, orphans, and risky areas.

The viewer reads the same `.aicontext/` data the agent uses. It never parses code itself, and it stays fully local.

### 11.2 How users open it

| Command | What happens |
|---|---|
| `prism view [--port N] [--no-open]` | Starts a local server on `127.0.0.1` (random free port by default, one-time token in the URL) and opens the graph in the default browser. Live-updates as the index changes. |
| `prism view --focus <target> [--depth 2]` | Opens straight into the **local graph** around a symbol/file (Obsidian's "local graph"). |
| `prism graph export --html <file>` | Single self-contained HTML file (data + JS inlined) — shareable, opens offline, no server. |
| `prism graph export --obsidian <dir>` | Generates an **Obsidian vault**: one Markdown note per module/file (and optionally per class/function) with `[[wikilinks]]` for imports/calls, YAML frontmatter (rank, risk, owner, language), and tags (`#module/pricing`, `#risk/high`). Opening the folder in Obsidian gives its native graph view, backlinks, and search over the codebase for free. |
| `prism graph export --mermaid\|--dot\|--graphml\|--json [--around <target> --depth N]` | For docs, Gephi/yEd, or small inline diagrams an agent can paste into a reply or PR. Mermaid/DOT exports without `--around` are capped (default 150 nodes) to stay readable. |
| MCP: `prism_graph_view_url` | Returns the local viewer URL (focused on a target if given) so the agent can tell the user "here's what I'm about to change." |

### 11.3 Viewer features

**Graph layers** (toggle in the UI; each is a different edge set over the same nodes):
- Import graph (module/file level) — default view.
- Call graph (symbol level).
- Test coverage links (symbol ↔ test).
- Co-change graph (from git history; edge weight = co-change strength).
- Route → handler → model chains.

**Levels of detail (semantic zoom)** — essential for large repos:
- Zoomed out: packages/modules as clustered super-nodes (edge thickness = aggregated link count).
- Zoom in or double-click a cluster: expands to files, then to classes/functions.
- Never render more than the configured node cap (default 5,000 visible) at once; collapse the rest into clusters.

**Visual encoding** (each switchable, with a legend):
- Node size: PageRank (default), lines of code, fan-in, or blast-radius size.
- Node color: module/folder (default), community cluster, risk score (heat scale), owner, language, last-changed recency, or open audit findings.
- Node shape/icon: module, file, class, function, test, route, model.
- Edge style: solid = static certainty, dashed = low-confidence resolution; arrows show direction.

**Interaction (Obsidian parity and beyond):**
- Hover → highlight the node and its direct neighbors, fade everything else.
- Click → side panel: signature, docstring, file:lines, callers/callees, tests, risk reasons, open findings, git owner/churn, and buttons to **Open in editor** (`vscode://file/…`, `cursor://…`, or configured command), **Copy `prism context` command**, **Show local graph**, **Show blast radius**.
- Search box with fuzzy match (same engine as `prism search`); results fly the camera to the node.
- Filters: by folder/glob, node kind, layer, hide tests, hide external/third-party, show orphans only, min rank, risk ≥ X, "changed since <ref>".
- Local graph mode with depth slider (1–4 hops).
- Path finder: shortest dependency path between two nodes ("how does `api/orders.py` reach `db/session.py`?").
- Overlays: blast radius of the selected node (dependents highlighted in rings by distance), audit heatmap, dead-code candidates, import cycles (highlighted in red).
- Diff mode: highlight nodes/edges added, removed, or changed since the last `AGENTS.md` refresh, the last audit, or a git ref — a visual view of drift.
- Physics controls like Obsidian (center force, repel, link force, link distance), pin/drag nodes, freeze layout, and save named views (filters + camera + layout) to `.aicontext/cache/views/` (or commit them if the team wants them shared).
- Light/dark theme; keyboard shortcuts (`/` search, `Esc` clear, `L` local graph, `B` blast radius).

**Live updates:** the server watches `manifest.json`; when `prism update` runs (e.g. from the agent's post-edit hook), it pushes a delta over Server-Sent Events and the viewer animates new/changed nodes (briefly pulsing) without resetting the layout. The user can literally watch the agent work.

**Agent activity trail:** every navigator call (`locate`, `context`, `impact`, `search`) appends a small event to `.aicontext/cache/activity.log` (symbol IDs only, local, capped, gitignored). The viewer streams it and highlights the nodes the agent is currently looking at, fading over time, so the user sees what the agent read and what it changed. Toggleable; off in exports.

### 11.4 Implementation

- **Frontend:** TypeScript app in `viewer/` (repo root), built with Vite into a static bundle shipped as package data in `prism/viewer_dist/`. End users never need Node; only PRISM developers do.
- **Rendering:** WebGL via **Sigma.js + Graphology** (handles tens of thousands of nodes; live `d3-force` layout with Obsidian's forces, plus a deterministic layered tier layout; Louvain community detection via `graphology-communities-louvain`). Alternatives: Cytoscape.js (richer layouts, slower at scale), `force-graph`/`3d-force-graph` (optional 3D mode later). Record the final choice as an ADR in `docs/adr/`.
- **All JS/CSS/fonts vendored in the bundle.** No CDN, no external requests — the viewer must work with the network unplugged.
- **Backend:** stdlib-only HTTP server (`http.server` + SSE) in `prism/viewer/server.py`; no FastAPI/uvicorn dependency. Endpoints map 1:1 to library functions:
  - `GET /api/graph?layer=import&level=module|file|symbol&root=<id>&depth=N&filters=…` → nodes + edges, already aggregated to the requested level.
  - `GET /api/node/<id>` → side-panel details (reuses the context-pack builder).
  - `GET /api/search?q=…`, `GET /api/path?from=…&to=…`, `GET /api/impact/<id>`, `GET /api/diff?since=…`.
  - `GET /api/events` → SSE stream of index deltas.
- **Security:** bind to `127.0.0.1` only; require the per-session token on every request; no endpoint can write source files or run commands. "Open in editor" is a URL scheme handled by the OS, not a server action.
- **Layout persistence:** store node positions in `.aicontext/cache/layout.json` so reopening is instant and the map stays stable between sessions (new nodes are placed near their neighbors instead of reshuffling everything).
- **Obsidian export** lives in `prism/writers/obsidian.py`, is deterministic (stable filenames from symbol IDs), and writes only to the target directory; re-export updates notes in place and removes notes for deleted symbols. It never touches `.obsidian/` config except, optionally, a graph color-group preset (`--with-graph-colors`).

### 11.5 Performance targets

- First paint of the module-level graph in **< 2 s** for a 100k-LOC repo; smooth interaction (≥ 30 fps, target 60) with 5,000 visible nodes on a typical laptop.
- Live delta from `prism update` to on-screen change in **< 1 s**.
- Self-contained HTML export ≤ 10 MB for a 100k-LOC repo at file level (symbol level opt-in).

