# Changelog

All notable changes to PRISM are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Graph viewer redesign: new layout with a node drawer, inspector and legend card; dark and light
  themes; bundled JetBrains Mono so it stays offline.
- Every node is clickable, with an inspector showing importance, links, risk, blast radius,
  callers, callees, tests, co-changed files, history, findings and smells, plus actions.
- Hover preview cards, an accessible virtualised node list, a search combobox, keyboard spatial
  navigation with screen-reader announcements, and a `?` shortcut for the help dialog.
- Monorepo-aware command detection: Django (`manage.py test`), vitest, jest and per-folder npm
  scripts, shared by the brief and the audit plan.
- Token-savings and workflow benchmark: `python -m tests.benchmarks.tokens [--repo --tasks]`.
- Full documentation set: guides, CLI and artifact references, architecture diagrams, ADR 0002,
  contributing guide, security policy and code of conduct.

### Changed
- Search stems terms, so bug-report wording matches identifiers, and ranks application code
  above tests and migrations unless the query asks for them. The search cache format is bumped
  and rebuilds automatically.
- Django's `tests.py` files are recognised as tests.
- The viewer server caches graph payloads and uses a store per thread.
- The brief's default Python test command is now `python -m pytest -q`.

### Fixed
- Minified and generated bundles (`*.min.js`, `*.bundle.js`, source maps, minified JS/TS) are no
  longer indexed; they produced hundreds of meaningless symbols.
- Concurrent viewer requests could collide while building the query cache on Windows.
- Stale temp-file cleanup could delete a cache that was still being built.
- The viewer showed "Failed to fetch" when its server stopped; it now explains what happened.
- Malformed numeric viewer parameters now return a client error instead of failing.
- CI type checks across Python versions.
- `prism search --help` lost the `[semantic]` extra name to Rich markup.
- The viewer's "Open in editor" preference no longer fails where browser storage is blocked.

## [0.1.0]

First implementation of the specification in CLAUDE.md.

### Added
- **Index:** discovery with scoped `.gitignore` and `.prismignore`, Python `ast` parsing and
  optional tree-sitter parsing for JavaScript, TypeScript, Go and Java, symbol table, import and
  call graphs with confidence, PageRank, extractors (routes, models, config keys, entry points,
  tests map, dead code, blast radius), health and git intelligence, deterministic writers.
- **Navigator:** `brief`, `search` (BM25, optional local embeddings), `locate`, `context`,
  `impact`, `module`, with a SQLite query cache.
- **Freshness:** incremental updates with a parse cache and lazy ranking, session-start and
  post-edit hooks, git hooks, `watch`, drift scoring and section staleness.
- **Narrator:** `AGENTS.md` with generated and narrative regions, module summaries,
  `refresh prepare` / `commit`, architecture decisions.
- **Auditor:** toolchain detection, static smells, `audit plan` / `record` / `update` / `report`
  with history diffs.
- **Visualizer:** `prism view` (local server with SSE live updates) and exports to HTML,
  Obsidian, Mermaid, DOT, GraphML and JSON.
- **Integrations:** Claude Code (skills, hooks, MCP, CLAUDE.md block), Cursor, Codex and generic
  `AGENTS.md`; MCP server; per-user consent with enable, pause and uninstall.
- `doctor` and `migrate`.
