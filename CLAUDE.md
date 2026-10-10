# CLAUDE.md — PRISM

PRISM is a persistent, local context layer for coding agents. It indexes code,
retrieves the files and symbols a request needs, and delegates reasoning to the
host agent. Package: `prism-ctx`; CLI: `prism`; Python 3.10+.

## 1. Problem

Reduce repeated repository exploration and deliver a small, useful working set.
Every agent-facing surface has a token budget. Prefer retrieval over dumping.

## 2. Five pillars

- Index: deterministic symbols, graphs, routes, configuration, tests and risk.
- Navigator: ranked, budgeted code, exact occurrences, callers and impact.
- Narrator: factual skeletons plus host-agent-written summaries on demand.
- Auditor: prioritized plans and validated findings; the host agent reasons.
- Visualizer: a local browser graph and deterministic portable exports.

## 3. Core principle

PRISM computes; the agent thinks. Core code never calls an LLM, needs an API key,
or makes a network call. No cloud service or telemetry. The host agent performs
narration and review through skills and tools. Optional local embeddings stay
offline and never download a model automatically.

## 4. Design principles

- Same source produces byte-stable index content: sorted keys and stable order.
  Timestamps belong only in manifest metadata.
- Updates are incremental: one file should take under 0.5 seconds. Warm queries
  target p95 below 200 milliseconds on a 100k-LOC repository.
- JSON and Markdown artifacts remain plain and portable.
- Core stays agent-agnostic; installers belong in `prism/integrations/`.
- Never modify indexed user source. Checked patches belong in PRISM's cache.
- Consent is per repository and per user. No automatic enabling or scanning.
  Agents must never run `prism init`, `prism scan`, `prism enable`, or global
  installation unless explicitly requested. Use isolated scratch repos in tests.
- Installers are idempotent, declare every changed file, and restore backups.

## 5. Session workflow

Brief → request packet → targeted reads → edits → incremental update → occasional
on-demand narrative refresh. A good packet is used directly rather than followed
by another repository-wide search. Literal lists are exhaustive only when marked.

## 6. Architecture

Discovery → parsing → symbols and graphs → extractors → health and Git → drift →
writers. Typed stage boundaries, no backwards imports. Navigator reads artifacts;
CLI, MCP, hooks and viewer are thin surfaces over shared library operations.
The host agent performs all model reasoning.

## 7. Index artifacts

Full specification: [index artifacts](docs/spec/07-index-artifacts.md).

## 8. Navigator

Full specification: [navigator and packets](docs/spec/08-navigator.md).
Area rules: [navigator CLAUDE.md](prism/navigator/CLAUDE.md).

## 9. Freshness and narrator

Full specification: [freshness and narrator](docs/spec/09-freshness-narrator.md).

## 10. Auditor

Full specification: [auditor](docs/spec/10-auditor.md).
Audit defaults to read-mostly; applying fixes and publishing require authorization.

## 11. Viewer

Full specification: [viewer](docs/spec/11-viewer.md).
Area rules: [viewer CLAUDE.md](viewer/CLAUDE.md).

## 12. Integrations

Full specification: [integrations and consent](docs/spec/12-integrations.md).
Area rules: [integration CLAUDE.md](prism/integrations/CLAUDE.md).

## 13. Skills

Full specification: [shipped skills](docs/spec/13-skills.md).
Skills are product code: commands, flags and fields must exist and be tested.

## 14. CLI

Full specification: [CLI](docs/spec/14-cli.md). Use command help for current flags.

## 15. Layout and stack

`prism/`: core, discovery, parsing, graph, extractors, health, drift, writers,
incremental, navigator, narrator, audit, hooks, integrations, MCP and viewer.
`tests/`: unit, integration, fixture, golden, benchmark and skill checks.
`viewer/`: TypeScript/Vite/Sigma.js sources; `prism/viewer_dist/`: generated bundle.
`docs/`: specifications, ADRs, measurements and current phase status.
Python AST is the base parser; tree-sitter and embeddings are optional extras.
SQLite caches are disposable; canonical JSON remains the source of truth.

## 16. Engineering conventions

- Typed public functions; keep runtime dependencies small and lazy.
- Ruff lint/format; strict mypy for `prism/`.
- Only `writers/` writes index artifacts, with audit/refresh using writer helpers.
- No duplicated business logic between CLI, MCP, hooks or viewer API.
- Schema changes require versioning, migration and schema/skill tests.
- Keep engine fingerprints in packet cache keys to invalidate changed behavior.
- Windows is a primary platform: preserve CRLF, paths and safe shell quoting.
- Conventional Commits: `type(scope): summary`. Preserve unrelated local edits.

## 17. Validation

```text
python -m ruff check .
python -m mypy -p prism
python -m pytest -q
```

For viewer changes also run `npm run test` and `npm run typecheck` in `viewer/`.
Fixtures isolate consent. The suite blocks external networking. Validate budgets,
golden determinism, incremental equivalence, installer reversibility, consent,
surface parity and supported skill commands. Paid or network-dependent benchmark
scripts stay outside pytest collection and core code.

## 18. Metrics

Original targets: [metrics specification](docs/spec/18-metrics.md).
Measured results take precedence over projected savings. Report correctness,
cost, recall and uncertainty together; do not advertise unvalidated targets.

## 19. Current work

[Phase status](docs/phase-status.md) records verified implementation coverage.
[Master improvement plan](docs/master-improvement-plan-2026-10-11.md) defines the
current token-efficiency tasks and acceptance gates.

## 20. Before adding anything

Check: offline core, consent, bounded context, deterministic artifacts, incremental
performance, schema compatibility, shared library logic, and no user-source writes.
If a proposal violates these principles, flag it instead of working around them.
