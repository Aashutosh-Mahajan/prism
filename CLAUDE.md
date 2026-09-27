# CLAUDE.md — PRISM

> **PRISM is a persistent, local context layer for AI coding agents.**
> It maps a codebase once, keeps that map fresh as the code changes, and lets any coding agent (Claude Code, Cursor, Codex, etc.) jump straight to the exact files, functions, and line ranges a task touches — instead of re-reading the whole repository at the start of every session. It also ships an **audit skill** that turns the user's own coding agent into a codebase auditor, and an **Obsidian-style interactive graph view** of the whole codebase — all with no API keys and no cloud service.

This file is the source of truth for any coding agent building PRISM. Read it fully before writing code. When something here conflicts with a quick instinct, this file wins; when something here seems wrong, raise it with the user instead of silently diverging.

- Package: `prism-ctx` (PyPI) · CLI: `prism` · Python 3.10+
- Repo: `github.com/algosmiths/prism` · Built by AlgoSmiths

Implementation tracking: [docs/phase-status.md](docs/phase-status.md) records verified coverage,
test results, and remaining phase acceptance work. The roadmap below describes the target,
not a declaration that every phase is complete.

**Contents:** 1 Problem · 2 Five pillars · 3 Core principle · 4 Design principles · 5 Session walkthrough · 6 Architecture · 7 `.aicontext/` · 8 Navigator & MCP server · 9 Freshness & Narrator · 10 Auditor · 11 Visualizer · 12 Integrations, opt-in & discovery · 13 Shipped skills (skill plans) · 14 CLI · 15 Tech stack & layout · 16 Conventions · 17 Testing · 18 Metrics · 19 Roadmap · 20 Checklist

---

## 1. The Problem, Precisely

Every new agent session starts blind. To make even a one-line change in a function, a coding agent typically:

1. Lists directories, greps, and opens many files to figure out where things live.
2. Reads whole files to find one function and its callers.
3. Re-discovers conventions, entry points, and architecture it already learned yesterday.

On a mid-sized repository this "orientation tax" is most of the session's tokens (the brief estimates 80–95%), and it is paid again in every new session because the agent's context window is wiped.

## 2. What PRISM Does — Five Pillars

| Pillar | What it is | Who does the work |
|---|---|---|
| **1. Index** | A deterministic map of the codebase: symbols, call graph, import graph, PageRank importance, routes, models, config, health, git history. Stored in `.aicontext/`. | PRISM (static analysis, no LLM) |
| **2. Navigator** | Targeted retrieval. The agent asks "where is `apply_discount` and what does it touch?" and gets a small **context pack**: exact file + line range, callers, callees, related tests, blast radius — within a token budget. Exposed via CLI, MCP server, and a skill. | PRISM (queries over the index) |
| **3. Narrator** | `AGENTS.md` plus per-module summaries: the human-quality "here's how this project works" briefing. PRISM generates the factual skeleton; the **user's own coding agent** writes the narrative parts via the `prism-refresh` skill. Refreshed only when changes are significant. | PRISM (skeleton + staleness tracking) + host agent (prose) |
| **4. Auditor** | A codebase audit (bugs, risky code, failing tests, security smells, dead code). PRISM produces a prioritized audit plan from its index; the **user's own coding agent** executes it by following the `prism-audit` skill, runs the tests, and records findings back into PRISM. | PRISM (plan, schema, report) + host agent (reasoning, running tests) |
| **5. Visualizer** | An interactive, Obsidian-style graph of the codebase in the browser: force-directed, zoomable from packages down to functions, colored by module/risk/owner, with local-graph mode, search, blast-radius and audit overlays, live updates as the agent edits, and export to an Obsidian vault. | PRISM (local viewer over the index) |

**Mental model:** PRISM is a *permanent, local context window* that lives on the user's machine, next to the code, and updates itself. The agent's own context window becomes a small, focused working set loaded on demand from PRISM.

## 3. Core Principle: "PRISM computes, the agent thinks."

This is the single most important architectural rule.

- PRISM itself **never calls an LLM API** and **never requires an API key**. Everything PRISM does on its own is deterministic static analysis and bookkeeping.
- Anything that needs language-model reasoning (writing `AGENTS.md` prose, module summaries, auditing code, judging whether something is a bug) is **delegated to the host coding agent the user is already running**, through **skills** (instruction files) and **tools** (CLI / MCP) that PRISM installs into the repo.
- The user pays nothing extra and sends nothing to any new service. If they use Claude Code, Claude Code does the thinking with the user's existing plan/credentials. Same for Cursor, Codex, etc.
- Headless/CI use is supported by running the host agent in headless mode (e.g. `claude -p "run the prism-audit skill"`), not by adding an API client to PRISM.

A direct LLM provider mode is an explicit **non-goal for v1**. If it is ever added, it must be an optional extra (`pip install prism-ctx[llm]`), off by default, and nothing else may depend on it.

## 4. Non-Negotiable Design Principles

Check every feature and PR against these. Flag violations; don't implement around them.

1. **Local and offline.** No network calls from PRISM's core. No cloud, no telemetry, no required Docker, no editor plugin requirement. Nothing leaves the user's machine.
2. **No API keys.** See Section 3.
3. **Deterministic index.** Same code in → same `.aicontext/` out (byte-stable JSON: sorted keys, stable ordering, no timestamps inside content files; timestamps only in `manifest.json`).
4. **Incremental by design.** One changed file → one re-parse + local graph patch, under **0.5 s**. Full rescans only on first run, schema upgrades, or `--full`.
5. **Retrieval over dumping.** PRISM's job is to make the agent read *less*. Every output surface has a token budget. Never design a feature that encourages loading the whole index into context.
6. **Plain, portable artifacts.** JSON + Markdown, documented schemas, zero lock-in. Any tool can read `.aicontext/` with a file read.
7. **Zero-config first run.** `prism init && prism scan` works in any supported repo with no configuration.
8. **Agent-agnostic core, agent-specific adapters.** The core knows nothing about Claude Code or Cursor. Integrations live in `prism/integrations/` and only install files/config.
9. **Safe by default.** PRISM never modifies user source code. The audit skill is read-mostly: it must not fix, commit, push, or run destructive commands unless the user explicitly asks.
10. **Opt-in, per project, per user.** Installing PRISM does nothing to any project. PRISM runs in a repo only after the user explicitly enables it there (`prism init`), and can be paused or removed at any time. No auto-scan, no auto-init, no background activity in repos the user hasn't chosen. Agents must never run `prism init` or `prism scan` on their own initiative (Section 12.1).

## 5. How It Feels — Session Walkthrough (the target experience)

A user runs Claude Code in a repo where `prism init --agent claude-code` has been run.

1. **Session starts.** A `SessionStart` hook runs `prism brief`, which injects `.aicontext/AGENTS.md` (≤ 600 tokens) plus a one-line freshness status ("index fresh · 3 files changed since last scan, auto-updated"). The agent now knows the project's shape without reading a single file.
2. **User asks:** "The discount is applied twice when a coupon and a sale overlap — fix it."
3. **Agent navigates, doesn't scan.** Following the `prism-context` skill, it calls `prism_search("discount coupon sale")` → top hit `pricing.discounts.apply_discount` → `prism_context("pricing.discounts.apply_discount")` returns:
   - definition at `src/pricing/discounts.py:42-88`
   - 3 callers (`checkout/cart.py:117`, `checkout/cart.py:203`, `api/orders.py:58`)
   - related test file `tests/pricing/test_discounts.py`
   - co-changed file `pricing/rules.py`, open audit finding `F-012` on this function
   - "read list" totalling ~1,400 tokens.
4. **Agent reads only those ranges**, fixes the bug, runs the related test.
5. **Index stays fresh.** A `PostToolUse` hook on Edit/Write runs `prism update` for the touched file (~0.2 s). The drift score for this change is low, so `AGENTS.md` is not flagged stale.
6. **Weeks later**, after a new `payments/` module and a refactor of `checkout/`, accumulated drift crosses the threshold. The next `SessionStart` says: "AGENTS.md sections `architecture`, `checkout` are stale — run the prism-refresh skill." The agent refreshes just those sections, reading only the changed modules' context packs.
7. **Anytime, the user can see it.** `prism view` opens an Obsidian-style graph of the codebase in the browser. With it open during the session above, the user watches `apply_discount` and its callers light up as the agent reads them, and sees the node pulse when the edit lands.

That flow — **brief → search → context pack → targeted read → edit → auto-update → occasional narrative refresh** — is the product. Every design decision should make it faster, cheaper, or more reliable.

## 6. System Architecture

```
                ┌──────────────────────────── PRISM core (deterministic) ─────────────────────────────┐
 source files → │ Discovery → Parsing → Symbols+Graph → Extractors → Health+Git → Drift → Writers     │ → .aicontext/
                │                                     ▲                                                │
                │                        incremental patcher (hash cache)                              │
                └───────────────┬───────────────────────────────┬─────────────────────────────────────┘
                                │                               │
                      Navigator (query engine)          Narrator/Audit bookkeeping
                     locate · context · impact ·        skeleton AGENTS.md · staleness ·
                     search · brief                     audit plan · findings store · reports
                                │                               │
                ┌───────────────┴───────────────┐               │
                │ Surfaces: CLI · MCP server ·  │◄──────────────┘
                │ hooks · skills · graph viewer │
                └───────────────┬───────────────┘
                                │
                     Host coding agent (Claude Code / Cursor / Codex …)
                     does all LLM reasoning: narrative, audit, fixes
```

### 6.1 Pipeline stages (Index)

Sequential, each stage independently testable, communicating through typed dataclasses (never loose dicts, never global state). No stage imports from a later stage.

| # | Stage | Responsibility |
|---|---|---|
| 1 | **Discovery** | Walk repo; apply `.gitignore`, `.prismignore`, built-in ignores (venvs, `node_modules`, build dirs, binaries, files > size limit). |
| 2 | **Language detection** | By extension + shebang; route to parser. |
| 3 | **Parsing** | Per-language parser behind `BaseParser` → normalized `ParsedFile` (symbols, imports, calls, docstrings, line ranges, decorators). Python `ast` first; tree-sitter later. |
| 4 | **Symbol table** | Fully qualified symbol IDs (`pkg.module.Class.method`), signatures, line ranges, docstring first line, visibility (public/private). |
| 5 | **Graph build** | Import graph (module level) + call graph (symbol level, best-effort static resolution with confidence flags). |
| 6 | **Ranking** | PageRank on both graphs → importance scores used everywhere for ordering and budgeting. |
| 7 | **Extractors** (pluggable) | Routes/endpoints, ORM models, config & env vars, entry points (`__main__`, CLI defs, `main()`), test↔code mapping, dead-code candidates, blast radius (reverse transitive deps), static smells (for audit plan). |
| 8 | **Health + Git** | Complexity (cyclomatic), churn, ownership, co-change pairs from `git log`; coverage if a coverage file exists. Risk = f(complexity, churn, coverage, centrality). Git is optional — degrade gracefully without it. |
| 9 | **Drift** | Compare new structural facts to the previous manifest; compute drift score and section-level staleness (Section 9). |
| 10 | **Writers + Manifest** | Only module that writes `.aicontext/`. JSON files, skeleton `AGENTS.md`, `manifest.json` with SHA-256 per file, schema version, PRISM version. |

### 6.2 Incremental patcher

- `manifest.json` stores SHA-256 + mtime per source file.
- `prism update [--files a.py b.py]` re-parses only changed/added files, removes deleted ones, patches the symbol table and graph edges touching those files, then re-runs ranking **lazily** (full PageRank only when edge changes exceed a threshold; otherwise keep scores and mark "approx").
- Target: ≤ 0.5 s per changed file on a 100k-LOC repo. Enforced by a benchmark test.

## 7. The `.aicontext/` Directory

Committed to git by default so the whole team (and every AI session) benefits from one scan. `cache/` and `audit/scratch/` are gitignored (added automatically by `prism init`).

```
.aicontext/
├── AGENTS.md                 # ≤ 600-token session brief (skeleton by PRISM, narrative by host agent)
├── manifest.json             # versions, file hashes, drift state, section staleness, last scan/refresh
├── symbols.json              # every function/class/method: id, file, lines, signature, doc, callers, callees
├── dependency_graph.json     # module import graph + PageRank
├── call_graph.json           # symbol call graph + PageRank + resolution confidence
├── blast_radius.json         # per file / per public symbol: reverse transitive dependents (capped)
├── routes.json               # endpoints → handler symbols
├── models.json               # ORM/data models → fields → usages
├── config.json               # config keys & env vars → where read
├── tests_map.json            # symbol/file → related tests
├── health.json               # per-file risk: complexity, churn, coverage, centrality
├── git_intelligence.json     # co-change pairs, ownership, churn
├── modules/                  # per-module summaries, loaded on demand
│   └── <module>.md           #   skeleton facts + agent-written narrative
├── decisions/                # (Phase 5) ADR-style notes the agent records
├── audit/
│   ├── audit_plan.json       # generated by `prism audit plan`
│   ├── findings.json         # canonical findings store (via `prism audit record`)
│   ├── REPORT.md             # rendered by `prism audit report`
│   ├── history/              # previous reports for diffing
│   └── scratch/              # repro tests etc. (gitignored)
└── cache/                    # gitignored: SQLite query index, embeddings, parse cache,
                              #   viewer layout.json and saved views/
```

**Schema rules:** every JSON file carries `"schema_version"`. Schemas live in `prism/schemas/*.json` (JSON Schema) and are validated in tests. Breaking a schema = major version bump + migration in `prism migrate`.

### 7.1 Key schemas (abbreviated)

`symbols.json` entry:
```json
{
  "id": "pricing.discounts.apply_discount",
  "kind": "function",
  "file": "src/pricing/discounts.py",
  "lines": [42, 88],
  "signature": "apply_discount(cart: Cart, coupon: Coupon | None) -> Money",
  "doc": "Apply the best eligible discount to a cart.",
  "visibility": "public",
  "calls": ["pricing.rules.eligible_rules", "money.Money.__mul__"],
  "called_by": ["checkout.cart.Cart.total", "api.orders.create_order"],
  "rank": 0.0134,
  "tokens_est": 410
}
```

Context pack (output of `prism context`, JSON form; Markdown form is the default for humans/agents):
```json
{
  "target": {"id": "pricing.discounts.apply_discount", "file": "src/pricing/discounts.py", "lines": [42, 88]},
  "summary": "Apply the best eligible discount to a cart.",
  "callers": [{"id": "checkout.cart.Cart.total", "file": "src/checkout/cart.py", "line": 117}],
  "callees": [{"id": "pricing.rules.eligible_rules", "file": "src/pricing/rules.py", "lines": [10, 40]}],
  "tests": ["tests/pricing/test_discounts.py"],
  "co_changed": ["src/pricing/rules.py"],
  "blast_radius": {"files": 6, "top": ["src/checkout/cart.py", "src/api/orders.py"]},
  "risk": {"score": 0.71, "reasons": ["high churn", "no direct test coverage of coupon+sale path"]},
  "open_findings": ["F-012"],
  "read_list": [
    {"file": "src/pricing/discounts.py", "lines": [42, 88], "tokens_est": 410, "why": "target"},
    {"file": "src/checkout/cart.py", "lines": [110, 130], "tokens_est": 180, "why": "caller"}
  ],
  "budget": {"requested": 2000, "used": 1390}
}
```

Audit finding (see Section 10.4 for the full schema).

## 8. Navigator & MCP Server — Targeted Retrieval (the core value)

### 8.1 Query operations

| Command | MCP tool | Purpose |
|---|---|---|
| `prism brief` | `prism_brief` | Print `AGENTS.md` + freshness line. Used by SessionStart hook. |
| `prism locate <name>` | `prism_locate` | Resolve a symbol/file name (exact → qualified suffix → fuzzy). Returns candidates with file:lines. Ambiguity → ranked list, never a silent guess. |
| `prism context <target> [--budget N] [--depth D] [--with-source]` | `prism_context` | Build a context pack for a symbol, file, `file:line`, or route (`GET /orders`). Default budget 2,000 tokens. |
| `prism impact <target>` | `prism_impact` | Blast radius: what could break if this changes, plus tests to run. |
| `prism search "<text>"` | `prism_search` | Free-text search over symbol names, qualified IDs, docstrings, paths, comments, routes. BM25 locally (Phase 2); optional local embeddings (Phase 5, `prism-ctx[semantic]`, offline model). |
| `prism module <name>` | `prism_module` | Module summary from `.aicontext/modules/`. |
| `prism status` | `prism_status` | Index freshness, changed files, drift score, stale sections, last audit. |

### 8.2 Context pack assembly rules

1. Always include the target's exact location and signature.
2. Rank candidates (callers, callees, tests, co-changed, config/model touch-points) by: edge proximity × PageRank × co-change strength × recency.
3. Greedily fill the token budget; each item carries `why` so the agent can skip what's irrelevant.
4. `--with-source` inlines only the target's body (never whole files) when it fits the budget.
5. Include open audit findings and risk reasons for the target.
6. Output is stable and compact; Markdown by default, `--json` for tools.

### 8.3 Performance targets

- `prism locate` / `prism context` / MCP calls: **< 200 ms** p95 on a 100k-LOC repo (use the SQLite cache in `.aicontext/cache/`, rebuilt from the JSON artifacts if missing).
- Context pack default ≤ 2,000 tokens; brief ≤ 600 tokens.

### 8.4 MCP server (`prism mcp`)

The MCP server lets the host agent call PRISM as native tools instead of shelling out to the CLI and parsing text.

- **Transport:** stdio, local only, started by the host agent from the `.mcp.json` (or equivalent) entry that `prism init` adds with user consent. No network listener.
- **Implementation:** official MCP Python SDK in `prism/mcp/server.py`. Each tool is a thin wrapper over the same library function the CLI calls. No logic lives in the server.
- **Why it exists alongside the CLI:** structured JSON results (fewer parsing mistakes), tools are visible in the agent's tool list (more reliable use than remembered commands), the index stays loaded in memory (fast, < 200 ms), and it works for agents that can use MCP but have no shell.
- **Consent-aware:** on start it checks the per-user enable flag (Section 12.1). If PRISM is not enabled for this user or is paused, it exposes only `prism_status`, which reports that state.
- **Read-mostly:** only `prism_audit_record`, `prism_audit_update`, and `prism_refresh_commit` write, and only inside `.aicontext/`, through the writer layer. No tool edits source code or runs shell commands.
- **Errors:** return structured errors (`not_enabled`, `index_missing`, `ambiguous_target` with candidates, `not_found` with suggestions, `budget_exceeded`) instead of raising, so the agent can recover.

| Tool | Input | Returns |
|---|---|---|
| `prism_status` | — | enable state, freshness, changed files, drift, stale sections, audit summary |
| `prism_brief` | — | AGENTS.md text + freshness line |
| `prism_search` | `query`, `limit?` | ranked hits (id, kind, file, lines, score, snippet) |
| `prism_locate` | `name` | candidates (id, kind, file, lines, signature) |
| `prism_context` | `target`, `budget?`, `depth?`, `with_source?` | context pack (Section 7.1) |
| `prism_impact` | `target` | dependents by distance, tests to run, risk |
| `prism_module` | `name` | module summary |
| `prism_refresh_prepare` | `sections?` | refresh packet per stale section |
| `prism_refresh_commit` | `section`, `text` | validation result; resets drift on success |
| `prism_audit_plan` | `scope?`, `since?`, `depth?` | audit plan (Section 10.2) |
| `prism_audit_record` | `finding` | assigned ID, dedupe result, or validation errors |
| `prism_audit_update` | `id`, `status` | updated finding |
| `prism_audit_report` | — | report path + summary counts |
| `prism_graph_view_url` | `focus?`, `depth?` | local viewer URL (starts the viewer if the user allowed it) |

## 9. Freshness & Narrator — Keeping the Context Alive

### 9.1 Update triggers (all optional; installed by `prism init` only if the user accepts them)

| Trigger | Action |
|---|---|
| Host-agent hook after file edits (e.g. Claude Code `PostToolUse` on Edit/Write/MultiEdit) | `prism hook post-edit` → reads hook JSON from stdin, runs `prism update --files <path> --quiet`. Must never block or fail the agent: timeouts short, errors swallowed to a log. |
| Session start hook | `prism hook session-start` → incremental update of anything changed outside the agent (e.g. `git pull`), then prints `prism brief` output into the agent's context. |
| Git `post-commit` / `post-merge` / `post-checkout` hooks | `prism update --quiet` |
| Manual / file watcher | `prism update`, `prism watch` (Phase 5) |

Verify exact hook config formats against the current docs of each host agent at implementation time; keep them in `prism/integrations/<agent>/` only.

### 9.2 Drift scoring — what counts as a "major/important change"

Every update computes a **structural diff** and adds weighted points to the drift score of each affected `AGENTS.md` section / module summary:

| Change | Weight (default) |
|---|---|
| New or deleted module/package | 5 |
| New/removed/renamed **public** symbol | 2 |
| Public signature change | 2 |
| New/removed route, model, or config key | 3 |
| Import-graph edges added/removed between modules | 1 per edge (cap 5) |
| Symbol enters/leaves global top-20 by PageRank | 3 |
| New dependency in `pyproject`/`package.json`/etc. | 3 |
| Private body-only edits | 0 (index updates, narrative does not) |

When a section's score ≥ threshold (default 8, configurable), it's marked **stale** in `manifest.json`. `prism brief` and `prism status` surface stale sections and tell the agent to run the `prism-refresh` skill. Formatting-only and comment-only changes never add drift.

### 9.3 `AGENTS.md` structure

Hybrid: PRISM writes facts, the agent writes prose, inside marked regions. PRISM must never overwrite narrative regions; the agent must never edit generated regions.

```markdown
# <Project> — Agent Brief
<!-- prism:generated:facts -->   stack, languages, entry points, commands (test/lint/run), top modules by rank
<!-- prism:narrative:purpose -->  what the project does, for whom (2–3 sentences)
<!-- prism:narrative:architecture --> how the pieces fit, main data flow
<!-- prism:narrative:conventions -->  patterns to follow, gotchas
<!-- prism:generated:navigation -->   "Before reading files, use prism search/context …"
```

`prism refresh prepare [--sections ...]` emits exactly what the agent needs to write each stale section (relevant context packs, structural diff since last narration, token budget per section). `prism refresh commit <section> --file <md>` validates length/markers and writes it, resetting that section's drift. This keeps the agent's work bounded and verifiable.

## 10. Auditor — Agent-Driven Codebase Audit

### 10.1 Concept

PRISM ships an **audit skill** (`prism-audit`) — a precise set of instructions that tells the host coding agent how to audit this codebase: what to check, in what order, how to prove each finding, and how to record it. PRISM contributes what it's good at (prioritization from the index, detecting test/lint commands, schema validation, report rendering, history diffing). The host agent contributes what it's good at (reading code, reasoning about bugs, running and writing tests). **No API. No separate service.**

### 10.2 Commands

| Command | Purpose |
|---|---|
| `prism audit plan [--scope all\|changed\|<path>] [--since <git-ref>] [--depth quick\|standard\|deep]` | Writes `audit/audit_plan.json`: detected toolchain commands (tests, linters, type checker, coverage), prioritized targets with reasons and context-pack IDs, static smells, dead-code candidates, untested high-rank symbols, previous open findings to re-verify. |
| `prism audit record --json <finding.json>` (or stdin) | Validates and appends/updates a finding in `audit/findings.json`. Assigns stable IDs (`F-###`), dedupes by (file, symbol, category, fingerprint). |
| `prism audit update <id> --status fixed\|wontfix\|false_positive` | Lifecycle changes. |
| `prism audit report` | Renders `audit/REPORT.md` (summary, severity table, per-finding detail, diff vs previous audit: new / fixed / persisting), archives to `audit/history/`. |
| MCP: `prism_audit_plan`, `prism_audit_record`, `prism_audit_report` | Same, for MCP-capable agents. |

### 10.3 Audit plan prioritization

Target score = risk (complexity × churn × low coverage) + centrality (PageRank) + blast radius size + recency of change + static smell count + open prior findings. Depth caps the number of targets (quick ≈ 10, standard ≈ 30, deep ≈ 100).

Static smell detectors (cheap, deterministic, feed the plan — they are *leads*, not findings): bare/broad `except`, swallowed exceptions, mutable default args, `eval`/`exec`/`pickle.loads`/`subprocess(shell=True)`, SQL built by string formatting, hardcoded secret patterns, `TODO/FIXME/HACK`, very long functions, unreachable code, unused imports/symbols, missing awaits (where detectable).

### 10.4 Finding schema

```json
{
  "id": "F-012",
  "title": "Discount applied twice when coupon and sale overlap",
  "severity": "high",
  "category": "correctness",
  "confidence": "confirmed",
  "file": "src/pricing/discounts.py",
  "lines": [61, 74],
  "symbol": "pricing.discounts.apply_discount",
  "description": "Sale price is computed first, then the coupon percentage is applied to the original price and both reductions are summed.",
  "evidence": {"type": "failing_test", "command": "pytest .aicontext/audit/scratch/test_f012.py -q", "output_excerpt": "AssertionError: 72.0 != 81.0"},
  "suggested_fix": "Apply coupon to the post-sale price, or pick max(sale, coupon) per business rule — confirm rule with owner.",
  "status": "open",
  "found_in_audit": "2026-09-27T10:42:00Z",
  "fingerprint": "sha256:…"
}
```

- `severity`: `critical | high | medium | low | info` (rubric defined in the skill).
- `category`: `correctness | security | error_handling | concurrency | resource | performance | api_contract | test_gap | dead_code | maintainability | config`.
- `confidence`: `confirmed` (reproduced: failing test/command output), `likely` (strong static reasoning), `suspected` (needs human judgment). **Only `confirmed` may be `critical`/`high` without an explicit reason field.**

### 10.5 Integration back into navigation

Open findings appear in context packs and `prism status`. Fixed findings are re-verified on the next audit. `health.json` risk incorporates open findings.

The full audit procedure lives in `prism/templates/skills/prism-audit/SKILL.md` (shipped with this spec). Treat it as product code: version it, test it (see Section 17), and keep it consistent with the CLI.

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
- **Rendering:** WebGL via **Sigma.js + Graphology** (recommended: handles tens of thousands of nodes, ForceAtlas2 layout in a Web Worker, Louvain community detection via `graphology-communities-louvain`). Alternatives: Cytoscape.js (richer layouts, slower at scale), `force-graph`/`3d-force-graph` (optional 3D mode later). Record the final choice as an ADR in `docs/adr/`.
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

## 12. Host-Agent Integrations

`prism init [--agent claude-code|cursor|codex|generic|auto]` detects or asks which agent is used and installs only files/config. `prism uninstall-integration` removes them cleanly. All installed files carry a `prism-managed` marker so upgrades can rewrite them safely.

| Agent | What `prism init` installs |
|---|---|
| **Claude Code** | `.claude/skills/prism-context/`, `prism-refresh/`, `prism-audit/` (SKILL.md each); hooks in `.claude/settings.json` (SessionStart → `prism hook session-start`; PostToolUse matcher `Edit\|Write\|MultiEdit` → `prism hook post-edit`); MCP server entry in `.mcp.json` (`prism mcp` over stdio); a short managed block in the root `CLAUDE.md` pointing to `.aicontext/AGENTS.md` and the skills. |
| **Cursor** | `.cursor/rules/prism.mdc` (navigation rules + audit/refresh procedures), MCP config. |
| **Codex / others reading `AGENTS.md`** | Managed block in root `AGENTS.md`; MCP config if supported. |
| **Generic** | Managed block in root `AGENTS.md`/`CLAUDE.md` describing the CLI commands. |

Rules: merge into existing config files, never clobber user content; back up before modifying (`.aicontext/cache/backups/`); idempotent (running `init` twice changes nothing).

### 12.1 Opt-in model — the user decides, per project

PRISM must never run in a project the user hasn't explicitly chosen. Installing the package (`pip install prism-ctx`) changes nothing in any repository.

**Enabling is always an explicit user action:**
- `prism init` is the only way to enable PRISM in a repo. It runs interactively by default: it shows exactly which files it will create or modify (instruction block, hooks, MCP entry, skills, `.gitignore` lines) and asks for confirmation, with per-item choices (e.g. "install hooks? [Y/n]", "register MCP server? [Y/n]"). `--yes` skips prompts for scripted use only.
- The initial `prism scan` runs only when the user confirms it at the end of `init`, or runs it themselves.
- Nothing happens automatically after `init` except what the user accepted (e.g. if they declined hooks, the index updates only when they run `prism update`).

**Per-user consent, even in shared repos.** A repo can have `.aicontext/` and PRISM hooks committed by a teammate. That must not make PRISM run on every contributor's machine without asking. So every hook and the MCP server first check a **local, per-user enable flag**:
- Flag location: a user-level registry `~/.config/prism/repos.toml` (keyed by repo root path + repo ID from `manifest.json`), never a committed file.
- If the flag is absent, `prism hook session-start` prints at most one line into the agent's context ("This repo has a PRISM index. PRISM is not enabled for you here; run `prism enable` if you want to use it.") and does nothing else: no scan, no update, no writes. `prism hook post-edit` exits silently. The MCP server exposes only `prism_status`, which reports "not enabled."
- `prism enable` / `prism disable` toggle the flag for the current repo. `prism init` sets it for the user who ran it.

**Pausing and removing:**
- `prism pause` / `prism resume` stop and restart all automatic activity (hooks become no-ops) without removing anything.
- `prism uninstall-integration` removes every PRISM-managed block, hook, MCP entry, and skill, restoring backups. `prism uninstall-integration --purge` also deletes `.aicontext/`, after confirmation.
- `prism status` always shows the current state: `not initialized`, `initialized · not enabled for you`, `enabled`, or `paused`.

**Optional global setup is also opt-in and never auto-runs.** `prism install --global` (never run implicitly) only adds a short user-level note to the agent's global instruction file (e.g. `~/.claude/CLAUDE.md`): "If a repo has `.aicontext/` and PRISM is enabled for it, use PRISM for navigation. Never run `prism init` or `prism scan` unless the user asks." By default it does **not** make agents suggest PRISM in new repos. Suggestions only happen if the user chooses `--suggest`, and even then the agent may mention it once per repo, and only for large repos, never run it. `prism uninstall --global` removes the note.

**Rules for agents (enforced in every shipped skill and instruction block):**
- Never run `prism init`, `prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks in the current conversation.
- If PRISM is not initialized or not enabled, work normally without it. Don't nag. Mention it at most once, and only when global suggestions are on.
- `prism update` is allowed automatically only in repos where PRISM is enabled for this user (hooks do this; agents without hooks may run it after edits).

### 12.2 How a new agent session discovers PRISM

An agent only knows what is in its context when the session starts, so PRISM has to put itself there. It does this only in repos where the user enabled it, through several layers, so if one is missing another still works:

| Layer | Mechanism | Agents |
|---|---|---|
| 1. Instruction block | Managed block in the file the agent always reads at session start (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/prism.mdc`): "This repo is indexed by PRISM. Read `.aicontext/AGENTS.md`, use `prism search`/`prism context` before exploring files, check `prism status`." | All |
| 2. Session-start hook | `prism hook session-start`: consent check → incremental catch-up → prints the brief + freshness line into context. The agent gets the project map before the user types anything. | Claude Code (and others with hooks) |
| 3. MCP tools | `prism_*` tools appear in the agent's tool list. | MCP-capable agents |
| 4. Skill | `prism-context` skill description triggers at the start of coding tasks. | Claude Code |
| 5. Plain files | `.aicontext/AGENTS.md` and JSON are readable with no PRISM install at all. | All, as fallback |

**Hook robustness:** every hook must exit 0 quickly (hard timeout ~2 s for session-start, ~1 s for post-edit), never print errors into the agent's context, and do nothing if `prism` isn't installed, the repo isn't enabled for this user, or PRISM is paused. A broken or missing PRISM must never break or slow an agent session.

| Situation | What the agent sees |
|---|---|
| Enabled for this user, PRISM installed | Brief injected automatically; skill + MCP guide navigation. |
| Repo initialized by a teammate, not enabled for this user | One line saying PRISM is available and how to enable it. Nothing runs. |
| Committed `.aicontext/` but PRISM not installed | Hook not found → silent. Instruction block still points to `.aicontext/AGENTS.md` as plain files; the agent may use it read-only. |
| Never initialized | No PRISM files, so nothing happens. Only if the user turned on global `--suggest`, the agent may mention PRISM once. |
| Enabled but paused | Hooks are no-ops; `prism status` shows `paused`. The instruction block tells the agent the index may be stale. |
| Enabled, index stale (e.g. after `git pull`) | Session-start hook catches up incrementally; without hooks, the instruction block tells the agent to run `prism status` / `prism update` first. |

## 13. Shipped Skills — Skill Plans

Skills are the instruction files through which the host agent does PRISM's "thinking" work. They ship in `prism/templates/skills/<name>/SKILL.md` and are installed by `prism init` (with consent) into the agent's skill location (e.g. `.claude/skills/`). For agents without skills, the same procedures are rendered into their rules file (e.g. `.cursor/rules/prism.mdc`).

**Every skill follows the same structure:** frontmatter (`name`, `description` that clearly states when to trigger) → `prism-managed` marker → Purpose → When to use → Preconditions (consent + freshness check) → Procedure (numbered, each step names the exact CLI command and MCP tool) → Outputs → Guardrails. Skills are product code: versioned with PRISM, snapshot-tested, and checked by the skill consistency test (Section 17) so they only reference commands, flags, and fields that exist.

### 13.1 `prism-context` — navigation

| | |
|---|---|
| **Purpose** | Make the agent load only the code a task needs, using the index instead of scanning. |
| **Triggers** | Start of any coding task; any "where is / what calls / what breaks if" question. |
| **Preconditions** | `prism_status` = enabled. If not enabled/paused/missing → work normally, optionally read `.aicontext/AGENTS.md` read-only, never enable. |
| **Procedure** | brief (if not injected) → `search`/`locate` → `context` → read `read_list` only → `impact` before editing public symbols → edit → run listed tests → `update` if no hooks. |
| **Outputs** | Edits made with minimal reads; tests run from `impact`; findings marked fixed only with passing evidence. |
| **Guardrails** | Never run init/scan/enable/global install unasked; never load whole JSON artifacts; fall back to targeted grep (not full scan) when static analysis misses dynamic calls; never hand-edit `.aicontext/`. |

### 13.2 `prism-refresh` — narrative upkeep

| | |
|---|---|
| **Purpose** | Keep `AGENTS.md` and module summaries accurate with minimal token spend, by rewriting only sections that drifted. |
| **Triggers** | `prism_status` reports stale sections (offered after the current task is done), or the user asks to refresh the brief. |
| **Preconditions** | PRISM enabled; index fresh (`update` first if not). |
| **Procedure** | `refresh prepare` → read only the packet and referenced context packs → rewrite each stale section within its token limit (keep what's still true) → `refresh commit` per section → report what changed. |
| **Outputs** | Updated narrative regions; drift reset for committed sections. |
| **Guardrails** | Never touch `prism:generated:*` regions or edit `AGENTS.md` directly; state only verified facts; respect the 600-token brief limit. |

### 13.3 `prism-audit` — agent-driven audit

| | |
|---|---|
| **Purpose** | Turn the host agent into an evidence-based auditor using PRISM's prioritization, with no API or external service. |
| **Triggers** | "Audit / review / health-check the codebase", "find bugs", "what's broken", "check before I merge". |
| **Preconditions** | Scope and depth determined; PRISM enabled (if not, ask the user; if they decline, audit without PRISM and report in chat). |
| **Procedure** | 0 scope & safety → 1 preflight (`status`, `audit plan`) → 2 baseline (tests, type check, lint, coverage) → 3 re-verify prior findings → 4 targeted review per target with checklist → 5 prove (repro in `audit/scratch/`) → 6 `audit record` each finding → 7 `audit report` + summary to user. |
| **Outputs** | `audit/findings.json`, `audit/REPORT.md`, new/fixed/persisting diff, chat summary with top findings and next steps. |
| **Guardrails** | Read-mostly; no fixes/commits/pushes unless asked; no destructive or production-touching commands; ask before tests needing network/DB/Docker; repro files only in `audit/scratch/`; never print secrets; `critical`/`high` need confirmed evidence or a stated reason. |

### 13.4 Future skills (not in v1)

`prism-setup` (walks a user through `prism init` choices when they ask for it; installed only by `prism install --global`), `prism-decisions` (records architecture decisions into `.aicontext/decisions/`), `prism-onboard` (produces a human onboarding tour using the graph viewer).

## 14. CLI Surface (complete)

```
prism init [--agent ...] [--no-hooks] [--no-mcp] [--yes]   enable PRISM in this repo (interactive, shows every change first)
prism enable | disable                             per-user consent for this repo (local, never committed)
prism pause | resume                               stop/restart all automatic activity without removing anything
prism uninstall-integration [--purge]              remove all PRISM-managed files (and optionally .aicontext/)
prism install --global [--suggest] | uninstall --global   optional user-level note for agents (never auto-runs)
prism scan [--full] [--lang ...]                    full index build
prism update [--files ...] [--quiet]                incremental update
prism status [--json]                               freshness, drift, stale sections, audit summary
prism brief                                         AGENTS.md + freshness line
prism locate <name> | context <target> | impact <target> | search "<q>" | module <name>
prism refresh prepare [--sections ...] | refresh commit <section> --file <md>
prism audit plan | record | update | report
prism hook session-start | post-edit               called by host-agent hooks (stdin JSON)
prism mcp                                           run MCP server (stdio)
prism migrate                                       upgrade .aicontext/ schemas
prism view [--focus <target>] [--port N]           interactive Obsidian-style graph in the browser (local)
prism graph export --html|--obsidian|--mermaid|--dot|--graphml|--json [--around <t>]
prism doctor                                        diagnose setup (hooks, MCP, schema, git)
```

Exit codes: 0 ok, 1 user error, 2 index missing/stale beyond repair, 3 internal error. Every command supports `--json` where output is structured. Output is quiet and machine-friendly by default in hook mode.

## 15. Tech Stack & Repository Layout

- Python 3.10+, packaged with `pyproject.toml` (hatchling or setuptools), entry point `prism`.
- CLI: `typer` (or `click`). Output: `rich` for humans, plain for `--quiet/--json`.
- Parsing: stdlib `ast` (Phase 1); `tree-sitter` + language grammars (Phase 5) behind `BaseParser`.
- Graph: `networkx` (PageRank) — or a small in-house implementation if dependency weight matters.
- Search: in-house BM25 or `rank-bm25`; optional `[semantic]` extra with a small local embedding model.
- Graph viewer: TypeScript + Vite + Sigma.js/Graphology (WebGL), prebuilt and shipped as package data; stdlib `http.server` + SSE backend (Section 11).
- Query cache: stdlib `sqlite3`.
- MCP: official MCP Python SDK (stdio server).
- Git: `git` CLI via `subprocess` (no GitPython dependency required).
- Schemas: `jsonschema` for validation in tests and `audit record`.
- Keep runtime dependencies minimal; heavy ones go behind extras.

```
prism/
├── prism/
│   ├── cli.py
│   ├── config.py                 # prism.toml / [tool.prism] in pyproject
│   ├── core/                     # dataclasses shared by all stages (ParsedFile, Symbol, Edge, …)
│   ├── discovery/                # scanner, ignore rules, language detection
│   ├── parsing/                  # base_parser.py, python_ast.py, (treesitter/ later)
│   ├── graph/                    # symbol_table.py, import_graph.py, call_graph.py, ranking.py
│   ├── extractors/               # base.py (Extractor interface + registry), routes, models, config,
│   │                             # entry_points, tests_map, dead_code, blast_radius, smells
│   ├── health/                   # complexity.py, git_intel.py, risk.py
│   ├── drift/                    # structural_diff.py, scoring.py, staleness.py
│   ├── writers/                  # json_writer.py, agents_md.py, modules_md.py, manifest.py
│   ├── incremental/              # hash_cache.py, patcher.py
│   ├── navigator/                # locate.py, context_pack.py, impact.py, search.py, budget.py, cache_db.py
│   ├── narrator/                 # refresh_prepare.py, refresh_commit.py, markers.py
│   ├── audit/                    # plan.py, record.py, report.py, fingerprint.py, toolchain_detect.py
│   ├── mcp/                      # server.py (tools map 1:1 to navigator/audit functions)
│   ├── viewer/                   # server.py (stdlib HTTP + SSE), api.py (graph aggregation, LOD, path finder)
│   ├── viewer_dist/              # prebuilt frontend bundle (generated at release; do not edit by hand)
│   ├── hooks/                    # session_start.py, post_edit.py
│   ├── integrations/             # claude_code/, cursor/, codex/, generic/  (installers only)
│   ├── schemas/                  # JSON Schemas for every artifact
│   └── templates/
│       ├── skills/               # prism-context/, prism-refresh/, prism-audit/  → SKILL.md
│       └── agents_md/            # AGENTS.md skeleton template
├── tests/
│   ├── unit/                     # one module per source module
│   ├── integration/              # full pipeline on fixture repos
│   ├── fixtures/repos/           # tiny (5 files), small (20), medium (80), + one with seeded bugs
│   ├── benchmarks/               # scan/update/query latency, token-savings harness
│   └── skills/                   # checks that skills reference only real commands/fields
├── viewer/                       # frontend source (TypeScript, Vite, Sigma.js) → builds into prism/viewer_dist/
├── docs/
├── pyproject.toml
├── README.md
└── CLAUDE.md                     # this file
```

## 16. Coding Conventions

- `ruff` (lint + format) and `mypy --strict` on `prism/`. Type hints on everything public.
- Stages expose one entry function with typed input/output; no cross-stage globals; no backwards imports.
- Only `writers/` writes into `.aicontext/` (and `audit/record.py`/`narrator/refresh_commit.py`, which go through writer helpers).
- New extractors implement `Extractor` and register via the registry — no pipeline edits needed.
- The MCP server and CLI are thin wrappers over the same library functions. Never implement logic in both.
- All user-facing text that ends up in an agent's context (brief, context packs, skills) is treated as a token budget: concise, no decoration.
- Integration installers must be idempotent and reversible.
- **Dogfood:** PRISM must index itself. Keep `.aicontext/` for this repo up to date and use `prism context` while developing PRISM.

## 17. Testing Strategy

- **Unit:** every stage and navigator function on synthetic inputs.
- **Golden files:** `.aicontext/` output for each fixture repo is snapshot-tested (determinism check: two runs → identical bytes).
- **Incremental equivalence:** for random edit sequences on fixtures, `scan` from scratch ≡ `scan` + N×`update`. This is the most important correctness test.
- **Performance:** benchmarks assert update ≤ 0.5 s/file, query ≤ 200 ms p95, on the medium fixture and a generated 100k-LOC repo (CI job, not every commit).
- **Budget tests:** brief ≤ 600 tokens, default context pack ≤ 2,000 tokens (use a fixed tokenizer approximation, e.g. chars/4, documented).
- **No-network test:** run the full suite with sockets blocked; any network call fails the build.
- **Drift tests:** each weighted change type triggers the expected score; formatting-only changes score 0.
- **Audit tests:** `audit plan` on the seeded-bug fixture ranks seeded files in the top targets; `record` rejects invalid findings and dedupes; `report` diffs history correctly.
- **Skill consistency tests:** parse each shipped SKILL.md and assert every `prism …` command, flag, and JSON field it mentions exists in the CLI/schemas.
- **Integration installers:** snapshot the files written for each agent; running `init` twice is a no-op; uninstall restores backups.
- **Consent:** in a repo with committed PRISM config but no local enable flag, hooks and MCP perform zero writes and zero scans (assert filesystem unchanged); `pause` makes all hooks no-ops; hooks exit 0 within their timeout when `prism` is missing or broken; `pip install prism-ctx` alone creates no files anywhere.
- **Viewer:** API endpoint tests (aggregation levels, filters, path finder, token enforcement, 127.0.0.1 binding); Playwright smoke test that loads the viewer on the medium fixture offline (network blocked), searches a node, opens the side panel, and receives a live SSE delta after `prism update`; Obsidian export golden files and re-export idempotence.

## 18. Success Metrics

- **Token savings:** a benchmark harness replays scripted tasks on fixture repos and counts tokens read by an agent with vs. without PRISM. Target: ≥ 70% fewer tokens spent on orientation.
- **Freshness:** index never more than one hook-cycle behind the working tree when hooks are installed.
- **Accuracy:** `prism locate` top-1 correct ≥ 95% on a labeled query set; call-graph edge precision tracked per language.
- **Audit usefulness:** on the seeded-bug fixture, following `prism-audit` finds ≥ 80% of seeded bugs with `confirmed` evidence.
- **Viewer:** meets the Section 11.5 targets; a new user can find any symbol and see its callers visually within 10 seconds of `prism view`.

## 19. Roadmap (build in this order)

The Navigator is the core value, so it comes right after the index — earlier than in the original brief.

**Phase 0 — Foundations (days 1–3):** packaging, CLI skeleton, config, core dataclasses, schemas, fixture repos, CI (ruff, mypy, pytest, no-network).

**Phase 1 — Index (weeks 1–2):** discovery, Python `ast` parser, symbol table, import + call graph, PageRank, entry points, tests map, writers, manifest with hashes, skeleton `AGENTS.md`. `prism init`, `prism scan`, `prism status`.

**Phase 2 — Navigator (weeks 3–4):** `locate`, `context` (budgeted packs), `impact` (reverse deps), BM25 `search`, SQLite query cache, `prism brief`, MCP server, `prism-context` skill, Claude Code integration (skills + MCP + CLAUDE.md block).

**Phase 3 — Freshness + Narrator (weeks 5–6):** incremental patcher, hooks (`session-start`, `post-edit`, git hooks), git intelligence, health/risk, routes/models/config extractors, drift scoring and section staleness, `refresh prepare/commit`, `prism-refresh` skill, module summaries.

**Phase 4 — Auditor (week 7):** toolchain detection, static smells, `audit plan/record/update/report`, findings in context packs, `prism-audit` skill, seeded-bug fixture and audit tests.

**Phase 4.5 — Visualizer (week 8):** viewer API + stdlib server, Sigma.js frontend with import/call layers, semantic zoom, search, side panel, local graph, filters, color/size encodings; then live SSE updates, blast-radius/audit/cycle overlays, diff mode, path finder, saved views; exporters (`--html`, `--obsidian`, `--mermaid`, `--dot`, `--graphml`). A basic `prism graph export --html` can be pulled forward into Phase 1 as an early demo.

**Phase 5 — Breadth (week 9+):** tree-sitter multi-language (TS/JS, Java, Go), Cursor/Codex adapters, optional local semantic search, community detection for module grouping (shared with the viewer's cluster coloring), optional 3D graph mode, VS Code webview panel embedding the viewer, `decisions/` memory, `prism watch`, `prism doctor` polish.

Do not start a phase until the previous phase's tests (especially incremental equivalence and budgets) are green.

## 20. Before You Add Anything, Ask

1. Does PRISM now make a network call or need an API key? → Not allowed in core (Section 3).
2. Does it make the agent read *more* by default? → Rework it to be on-demand and budgeted.
3. Does it change a schema? → Version it, add a migration, update skills and schema tests.
4. Does it slow `update` past 0.5 s/file or queries past 200 ms? → Defer to full scan or cache it.
5. Does it require configuration before first use? → Find a sensible default.
6. Does it touch user source code or run risky commands? → Not without explicit user consent.
7. Is the logic duplicated between CLI, MCP, and the viewer API? → Move it into the library layer.

---
*Derived from the PRISM project brief (AlgoSmiths), extended with the navigator, MCP server, narrator, freshness, agent-driven audit, graph visualizer, and opt-in consent design.*
