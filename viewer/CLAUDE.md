# Viewer rules

- TypeScript + Vite + Sigma.js/Graphology; backend is local stdlib HTTP/SSE.
- Bind to loopback and require the session token for API access.
- Viewer API stays thin over shared index and navigator operations.
- Preserve semantic zoom, budgeted details and deterministic graph exports.
- Edit source here; do not manually edit prism/viewer_dist generated files.
- Run npm run test and npm run typecheck for viewer changes.
- Test live updates, token enforcement, path finding and export determinism.

Detailed specification: [viewer](../docs/spec/11-viewer.md).
