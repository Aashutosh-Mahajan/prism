# Module `prism.viewer.server`

<!-- prism:generated:facts -->
- Files: prism/viewer/server.py
- Docstring: `prism view`: a local, token-protected HTTP server for the graph viewer.
- Public API (by importance):
  - `running_viewer(root: Path) -> dict[str, Any] | None` — The viewer already serving this repo, if any (used by `prism_graph_view_url`). (prism/viewer/server.py:417)
  - `class ViewerServer` (prism/viewer/server.py:360)
  - `class EventHub` — Fans index/activity events out to connected SSE clients. (prism/viewer/server.py:46)
  - `class Watcher(threading.Thread)` — Polls the manifest and the activity log; publishes deltas. (prism/viewer/server.py:72)
  - `make_handler(backend: ViewerBackend, hub: EventHub, token: str, port_ref: list[int]) -> type[BaseHTTPRequestHandler]` (prism/viewer/server.py:146)
- Depends on: `prism.core`, `prism.viewer.api`, `prism.writers`
- Used by: `prism`, `prism.mcp`
- Tests: tests/integration/test_viewer.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
