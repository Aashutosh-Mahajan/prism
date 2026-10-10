# Changelog

All notable changes to PRISM are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Delivery parity: CLI and MCP return identical packet text (`tests/integration/test_surface_parity.py`);
  a tool call after the prompt hook shares the hook's session, so delivered code is a reference.
- MCP default profile is one tool, `prism_task` (`standard` adds status/context/impact).
- `prism doctor --session ID|latest`: whether PRISM was used in an agent session and why not.
- `prism filter -- <command>`: shortened test/build/git output that never drops a failure line,
  with the full output saved under `.aicontext/cache/tee/`.
- Packets name the exact test command (`Run: ...`); literal lists are grouped per file and a
  complete list may use up to 80% of the budget before occurrences are dropped.
- Antigravity: a `Stop` hook (`prism hook stop`) that sends the agent back once when a value
  change still leaves the old value in the code.
- Dart, Kotlin and Swift symbols, imports and calls (dependency-free declaration scanner).
- Warm local query process (`daemon = false` / `PRISM_DAEMON=0` to disable) and a light
  `prism task` entry that skips loading the full command line when it is running.
- Local ranking feedback from edits (`ranking_feedback = false` / `PRISM_FEEDBACK=0` to disable).
- ADRs 0003 (warm process), 0004 (output filtering), 0005 (ranking feedback).
- Benchmark runner support for parallel sessions with a private agent home per session.

- Packets: **Patch** (a checked, byte-exact diff for an explicit old → new change at the exhaustive sites, applied
  with one `git -c core.autocrlf=false apply`), **Twins** (the same function defined in several files), **Large
  files, read only** windows, **Batch** and **Done when** lines, archive/other-area demotion, nearest-test fallback.
- `prism find` (several searches in one call), `prism diff` (the patch alone), `prism task --detail brief`, MCP
  `prism_find` and `detail`.
- Finish-time check (`prism hook stop`) for Claude Code and Codex as well as Antigravity; opt-in `prism hook
  dedupe-read` (deny-only) and `prism init --dedupe-reads`; `prism init --all-skills` (only `prism-context` is
  installed by default).
- The prompt hook answers "explain the architecture" requests with the map (`prompt_overview`); the hook waits up
  to 16 s (installed timeouts 20 s).
- `prism doctor` warns when a managed instruction block is older than the running engine.
- Benchmark tooling: `analyze.py` (bootstrap intervals, pass^k, tokens per solved task), campaign folder and repository
  name overrides, hook-delivery records for every runner.

### Fixed
- Read dedupe remembers successful returned ranges rather than attempted reads, expires old
  coverage without extending it on new reads, and resets after compaction/resume.
- Test selection follows caller distance, includes unmapped fallback tests and discloses missing
  tests; an unrelated subproject's runner is never used, and test paths with spaces are quoted.
- Nested Git boundaries prevent ancestor-index discovery and ancestor-hook installation.
  Generated diffs include Git's subdirectory prefix and a skipped empty check is rejected.
- Scattered read hints remain bounded; numeric patch substitutions preserve decimal prefixes
  and multiple replacements cannot cascade into each other's newly written values.
- Added a balanced-session benchmark diagnostic with actual task-cluster resampling,
  missing-cell rejection, failure costs and explicit input/output token accounting.
- Cached task packets that quoted a translation, config or docs file (anything the code index
  does not list) were never served, so every such request was rebuilt. They are now verified by
  stored content hashes and served in about 0.04 s on a warm process. `--mode verify` never uses
  the packet cache.
- A block of a packet could be marked "shown earlier" because of another block of the same
  packet whenever a session was active.
- The overview map was empty when the request contained words that match nothing in the repository ("explain",
  "components"); it now falls back to the global map. `prism find --glob 'x/*'` no longer has its wildcard expanded by
  click on Windows.
- A gate or verify result no longer counts generic words of the request ("minimum doctor age") as the old value.
- Compact JSON is what the packet budget is measured against (indentation no longer shrinks the
  text form); `--json` output of `prism task` is compact.
- The directory tree was walked twice per query; stemming and tokenizing are cached.

### Added (earlier)
- Graph viewer: an Obsidian-style network arrangement (live d3-force simulation with centre,
  repel, link force and link distance; neighbours follow a dragged node; labels under nodes fade
  in with zoom; plain dots; optional arrows) and a *Layers* arrangement that draws dependency
  tiers as bands from foundations to entry points. An *Overview* tab names the most depended-on
  code, cycles, riskiest code, entry points and unconnected nodes. Nodes carry an `area` (colour
  by default) and, on directed layers, a dependency `tier`; payloads report `tiers`.
- Viewer motion: an intro in which a beam splits through a prism, views that bloom out of the
  package being opened, animated layout switches, and a light layer (selection ring, flows along
  the selected node's links, blast-radius ripples, live-update shockwaves). Reduced motion is
  respected throughout.
- Work log: hooks record each session's requests, edited files (resolved to functions) and
  retrieved symbols in `.aicontext/cache/worklog/` (local, gitignored, pruned after 30 days).
  The session-start brief adds a short summary of the most recent other session (≤ about 140
  tokens), task answers note earlier work on the same code when it fits the budget, and
  `prism note` / `prism recall` (MCP full profile: `prism_note`, `prism_recall`) add handoff
  notes and search older sessions. `worklog = false` or `PRISM_WORKLOG=0` turns it off.
- Optional semantic channel in `prism task` and the prompt hook (`semantic = true`): local
  embeddings of each symbol's name words, signature, docstring and first body lines are fused
  with lexical evidence. On the retrieval benchmark, paraphrased requests located 62% → 88%
  with no regression elsewhere (all cases 82% → 91%). Similarity-only blocks are marked
  `similar` and capped at medium confidence.
- A NumPy implementation of mean-pooled BERT sentence encoders (the default MiniLM model),
  numerically identical to sentence-transformers (max abs. difference ~1e-7), loading in
  about 0.2 s instead of importing PyTorch. `prism-ctx[semantic]` no longer needs PyTorch;
  `prism-ctx[semantic-full]` keeps sentence-transformers for other models.
- Incremental vector cache keyed by embedded-text hash; queries never embed the repository.
- Adaptive prompt delivery starts small and expands within the configured cap only when it
  completes edit evidence; undelivered attempts cannot consume session ranges. Default cap:
  2,000 estimated tokens. Explicit lower caps remain supported.
- Output-shape extensions avoid generic backtick-field literal searches; contracts without
  callers no longer reduce the primary builder's caller quota.
- `prism knowledge` and full-profile `prism_knowledge`: a bounded inspection of local project
  inventory, without loading the repository into the model.
- Versioned, bounded task-packet caches guarded by source and artifact revisions; unchanged
  requests reuse local work, and stale source never becomes a cached fresh answer.
- MCP task responses default to compact CLI-equivalent text. Structured consumers can request
  `format="json"`. Explicit MCP session IDs share delivered-range memory with CLI and hooks,
  including across server reconnects. No index-artifact schema change is required.
- Task compilation distinguishes object producers from UI consumers for explicitly described
  output shapes, includes matching small contracts, and ranks scalar settings as exact edits.
- Recovery ranges reserve output space; discarded blocks cannot enter delivered-session memory.
  Source is deduplicated across primary and supporting-definition assembly passes.
- Task ranking gives the leading edit operation and symbol names priority over repeated
  caller-body words, without dropping later acceptance criteria. Confidence uses returned
  source and cannot certify an absent leading topic from generic error matches alone.
- Global `--root` and task `--session` defaults accept options before the command;
  command options override them. Agent instructions reuse prompt-supplied context.
- Query-focused architecture maps and file symbol outlines through `prism task --mode overview`;
  `auto` recognizes broad orientation requests and `code` requests source explicitly.
- Exact task targets: `file::Class.method`, `file:line`, and bounded `file:start-end` reads.
- Local Python definition support and coherent small-class retrieval for cooperating methods;
  precise missing-source ranges and overlap-aware, hash-invalidated session references.
- Dependency-free diverse seed selection and bounded call-graph traversal for explanation requests.
- Reciprocal-rank fusion across body and symbol search, without duplicate per-file votes.
- Literal-search completeness tracks file/work caps and unavailable source instead of declaring
  partial scans exhaustive. Prompt headers are included in the hook budget.
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
- Viewer packages group files outside Python packages by folder (a TypeScript or Go folder is
  one package, not one per file); on this repository, 106 package nodes became 27.
- The viewer's own detail, search and impact lookups are no longer written to the agent activity
  trail, which had made the viewer report its user's clicks as agent activity.
- `graphology-layout-forceatlas2` is replaced by `d3-force` in the viewer bundle.
- One-file index update on the 124k-line benchmark: 0.77 s → 0.42–0.43 s (target ≤ 0.5 s met);
  the no-change check run before every query: 52 ms → 10–20 ms; full scan 15.6 s → 9.9 s.
  Discovery reuses directory-listing stat data, skips reading files whose extension is never
  indexed, and HEAD is read from `.git` instead of spawning git (falling back to git for
  unusual layouts).
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
