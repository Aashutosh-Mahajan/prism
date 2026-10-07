# Changelog

All notable changes to PRISM are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `prism task "<request>"` (MCP `prism_task`): one call returns the matching code, every exact
  occurrence of the strings, names and quantities the request mentions (an exhaustive list the
  agent need not grep), call sites with the calling line, tests that mention the code, impact,
  and an honest confidence. Whole small functions or windows, never file headers.
- `prism hook user-prompt`: the answer to the user's own request is added to the prompt before
  the model's first turn (Claude Code, Codex, Gemini CLI). Silent for chat and weak matches;
  bounded budget; code sent once per session; opt out with `prompt_context = false` or
  `PRISM_PROMPT_CONTEXT=0`.
- Query-time freshness: every navigator query checks the working tree and updates changed files
  first, under a cross-process update lock, so freshness no longer depends on hooks.
- Agent integrations for Codex (`.codex/config.toml`, `.codex/hooks.json`), Gemini CLI
  (`.gemini/settings.json`, `GEMINI.md`) and Antigravity (experimental), hooks for Cursor, and
  `prism doctor` checks for each installed agent.
- `prism mcp --profile lean|full` (default lean: `prism_status`, `prism_task`, `prism_context`,
  `prism_impact`).
- `prism brief --full`; `prism task --session`; `prism update a.py b.py`.
- Edit benchmark (`tests/benchmarks/edit_bench.py`): fresh agent per change request, executable
  checks, transcript measurement; retrieval benchmark (`tests/benchmarks/retrieval_eval.py`).
  Results: [agent benchmark 2026-10-07](docs/agent-benchmark-results-2026-10-07.md).
- A web-app test fixture (`tests/fixtures/repos/webapp`).
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
- The session brief an agent receives is compact (languages, commands, anything written by a
  human or agent, one line on using PRISM; ~100-150 tokens). Generated overviews, key
  dependencies, entry points, module rankings and placeholders are no longer injected, and the
  narrative sections are optional: research finds repository overviews raise cost without
  helping agents find files. `AGENTS.md` itself keeps its format.
- The instruction block and the `prism-context` skill are much shorter and no longer start with
  a status call. Cursor's always-on rule carries only the short block; audit, refresh and
  decision procedures are on-request rules.
- The post-edit hook starts the update in a detached process and returns in ~0.2 s (was ~0.7 s
  plus the update); hooks no longer import typer or rich and always speak UTF-8.
- Search stems short plurals (`kpis` meets `KPI`), ignores conversational filler, and widens a
  request with a small table of code-domain synonyms at half weight.
- A full `prism scan` leaves the query caches warm; `discover` no longer re-reads every large
  unchanged script file on every call. `prism init` detects Codex by `.codex/`, not by an
  `AGENTS.md` that many tools read.
- The `prism` entry point is `prism.entry:main` (reinstall the package to pick it up).
- Search stems terms, so bug-report wording matches identifiers, and ranks application code
  above tests and migrations unless the query asks for them. The search cache format is bumped
  and rebuilds automatically.
- Django's `tests.py` files are recognised as tests.
- The viewer server caches graph payloads and uses a store per thread.
- The brief's default Python test command is now `python -m pytest -q`.

### Fixed
- `prism update` with several files (`--files a b c`, the form agents write) failed with a usage
  error and left the index stale.
- `prism task` returned module headers and docstrings as the answer, missed UI copy that repeats a
  constant, and listed unrelated tests; ranking, merging of nested blocks, literals and test
  selection were reworked.
- A hook that timed out could still record its result as shown, making a later answer skip code
  the agent never received.
- Replacing an artifact while another process had it open raised a Windows sharing violation;
  writes now retry briefly.
- Re-initializing an agent twice rewrote Cursor's `hooks.json` with a different key order.
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
