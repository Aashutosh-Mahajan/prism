# Implementation status against CLAUDE.md

## Context engine upgrade — 2026-10-08

Latest follow-up: the actual checkout is enabled and indexed, with 21 narratives refreshed
and project-local MCP/hooks installed. Adaptive prompt packets and output-shape literal
handling were added. Full offline suite: **361 passed** before the final caller-quota change;
its **64-test** focused regression suite passed. Actual preflight edit-agent processed input:
**CLI -18.4%, MCP -20.5%**, all **18/18** matched checks per arm. This uses host-supplied
preflight evidence, not a native-host hook activation test. See the
[delivery report](token-saving-delivery-2026-10-08.md) for counters and limitations.

Shared task compilation now identifies scalar edit units, AST-verified output builders, small
declared contracts and bounded literal frontend constructions. CLI and native MCP share the
compact presentation; JSON remains available explicitly. Session IDs share delivered evidence
between CLI/hooks/MCP, and full packets have bounded local caches with revision and source-hash
checks. `prism knowledge` inspects the existing persistent repository inventory on demand.

Validation: full offline suite **357 passed**, Ruff and strict mypy passed; final cache-hardening
checks are recorded in [context engine validation](context-engine-validation-2026-10-08.md).
Fresh six-agent pilot: all frozen checks passed; processed input **CLI +13.8%, MCP -11.3%** against
the matched baseline. Cache-weighted input proxy: **CLI -6.2%, MCP -27.7%**. No large universal
token saving or completion of every roadmap acceptance target is claimed.

See [context engine guide](context-engine.md) for usage and the MCP format upgrade note.

Reviewed 2026-09-27. “Implemented” means code and relevant tests exist; it does not mean every acceptance target has been certified. CLAUDE.md remains the target specification.

| Phase | Status | Evidence and remaining work |
|---|---|---|
| 0 — Foundations | Implemented; release validation remains | Packaging, schemas, config, CLI, fixtures, strict checks and cross-platform Python CI exist. Added frontend CI and Python 3.14 coverage. Clean-wheel smoke tests and actual hosted CI results still need verification. |
| 1 — Index | Implemented | Discovery, Python parsing, graphs/ranking, extractors, manifests and artifact writers exist. Corrected the stale community-field golden; full suite now passes. |
| 2 — Navigator | Implemented; accuracy metrics pending | CLI/MCP retrieval, budgeted context, SQLite/BM25 search, brief and skills exist. Measured context p95 is 11.99ms on a synthetic 124k-line repo. Labeled locate accuracy and token-savings harness are still missing. |
| 3 — Freshness/Narrator | Partial relative to performance/architecture requirements | Cached parsing, lazy ranking, hooks, drift, refresh, health and Git intelligence exist with equivalence tests. Changed-file updates still rebuild derived graphs/extractors through build_index, rather than fully patching only affected graph regions. Measured one-file update is 0.7715s, exceeding 0.5s. |
| 4 — Auditor | Implemented; outcome metric pending | Plans, findings lifecycle, reports, seeded fixtures and skills exist. The specification's >=80% confirmed seeded-bug discovery metric is not yet demonstrated by an agent evaluation harness. |
| 4.5 — Visualizer | Implemented broadly; acceptance gaps remain | Live viewer, layers, drill-down, local focus, search, overlays, persistence, SSE and exporters exist. Fixed responsive collapse, path edges, search races, static filtering, legend and input validation issues. Browser CI, full keyboard graph navigation, exact low-confidence dashed edges, richer diff semantics and large-graph frame-rate/paint/SSE measurements remain. |
| 5 — Breadth | Partial | JS/TS/Go/Java tree-sitter support, Cursor/Codex adapters, local semantic search, communities, decisions, watch and doctor exist. Optional 3D graph and VS Code webview are absent. A real local embedding-model smoke test and broader parser accuracy validation remain. |

## Retrieval, freshness and multi-agent work (2026-10-07)

Driven by the agent benchmarks, which showed PRISM saving little because it added turns on top
of normal exploration. Delivered, with tests:

- **One-call answers** (`prism task`): exhaustive literal evidence, symbol-aware blocks, call
  sites, mention-based tests, impact, confidence. Retrieval benchmark: 13 of 14 labeled queries
  located (the 12 core ones all), mean answer about 850 tokens.
- **Footprint:** compact brief, short instruction block and skill, lean MCP profile, on-request
  Cursor rules. Context added at session start: about 460 tokens with the tool setup.
- **Freshness without hooks:** working-tree check on every query; update lock; detached
  post-edit update; cold caches warmed by `scan` and in the background by the prompt hook.
- **Agents:** Claude Code, Codex, Gemini CLI, Cursor (hooks), Antigravity (experimental), generic;
  idempotent and reversible for each; `doctor` checks them.
- **Measured** ([results](agent-benchmark-results-2026-10-07.md)): 15 live agents, 5 edit tasks,
  all 45 edits correct. Against agents with their normal tools: hook setup -34% total input,
  -15% billable-equivalent, -30% turns, -89% tool output, -26% time; tool setup -22% / -11% /
  -17% / -67% / -2%. One task (a single greppable method) saw no benefit.

Open: the 70% target is **not** demonstrated. On these tasks the fixed per-turn overhead of the
agent environment (about 77k tokens) bounds the savings in billable tokens; larger repositories,
vaguer requests and multi-session days are not yet measured. Semantic (embedding) retrieval
stays optional and unevaluated against the new lexical path. Antigravity's formats come from
third-party documentation; hooks for it are not documented. Windows-specific behaviors (file
sharing, code pages, first-open latency after files are written) were fixed as found; Linux and
macOS CI results are outstanding.

## Verified in this work

- Python: **192 tests passed** after fixing the stale golden and adding five boundary cases. Ruff and strict mypy passed.
- Frontend: **7 tests passed**, covering adjacency, exact path edges, response invalidation, findings legend, static package filters, unsupported layers/roots, and filtered degree values. Typecheck/build passed.
- Browser: at 390px viewport width the graph now measures 390px (previously 0px). Search results appear and Enter opens the matching package's details; related files are exposed as keyboard-operable buttons. Narrow layout defaults to collapsed filters and legend.
- Production bundle regenerated from source. CI now runs frontend tests/build and checks generated-asset drift; optional parser tests run in a dedicated job. Hosted CI has not been run from this workspace.
- Offline wheel build passed. Inspected the wheel for viewer backend/assets, schema and skill files, and verified the packaged JavaScript exactly matches the rebuilt source bundle. A fresh-environment installation smoke test remains pending.
- Performance harness added at `tests/benchmarks/run.py`; it uses temporary repositories and an isolated registry, without enabling PRISM in this checkout.

### Performance sample

Windows, Python 3.14, 442 files, 5,630 symbols, 124,087 generated module lines, no Git history:

| Operation | Observed | Target |
|---|---:|---:|
| Full scan including artifact writes | 12.156s | No hard scan limit specified |
| No-change update | 0.0533s | — |
| One-file comment edit update | **0.7715s**, exactly one file reparsed | <=0.5s |
| Context median, 25 calls over an open cache | 8.61ms | — |
| Context p95 | 11.99ms | <200ms |

These are one local benchmark run, not cross-machine guarantees. The query measurement excludes CLI startup and initial SQLite cache construction. Full scan and update run once each; repeated samples, Git history, dense graphs, memory, and UI timing are still needed.

## Since this review

Later on 2026-09-27 (see [CHANGELOG](../CHANGELOG.md) for the full list):

- Viewer: saved-view validation, stale overlay guards, keyboard node navigation with
  announcements, an accessible node list, and project-scoped export storage are done (item 3
  below); the viewer loads a 4,020-node symbol graph in about 0.2 s.
- Update latency: about 0.4 s in-process for a one-file edit on a 50k-line repository and about
  1 s through the post-edit hook; item 1 remains open for 100k-line repositories.
- An orientation-token harness exists (`tests/benchmarks/tokens.py`, item 6): 92% fewer tokens
  on a 50k-line Django + React app and 73% on PRISM itself. See [benchmarks](benchmarks.md).

## Next work in dependency order

1. Profile the changed-file update; reduce derived-stage work while preserving exact scan/update equivalence. Do not mark Phase 3 performance complete until the benchmark passes reliably.
2. Add browser smoke tests in CI for responsive geometry, keyboard search/panels, and a real update-to-SSE-to-render flow.
3. Finish viewer state contracts: saved-view validation, stale overlay response guards, accessible graph node navigation, and project-scoped export storage.
4. Measure graph paint, frame rate, export size, and live-update latency on the 100k-line fixture; improve based on profiles.
5. Complete structured module extraction in the viewer and split CLI command groups once behavioral tests cover the boundaries.
6. Add retrieval accuracy, per-language call precision, orientation-token and seeded-audit effectiveness evaluation datasets.
7. Smoke-test built wheels, optional parsers, and an already-installed local embedding model; verify hosted CI across supported platforms.
8. Only then implement the remaining optional Phase 5 3D and editor-webview features. They must retain offline operation and optional installation.

The detailed initial task rationale is in [the project audit](project-audit-2026-09-27.md). Its original findings are preserved as a baseline; this file records subsequent progress.
