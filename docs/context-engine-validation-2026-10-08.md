# Context engine implementation and validation — 8 October 2026

Follow-up: [local context build and preflight delivery measurements](token-saving-delivery-2026-10-08.md)
record the later adaptive-hook and literal-field fixes. This report retains the earlier tool-only pilot.

Implemented the shared local-context upgrade in the Prism working tree. The existing portable
index, source postings, graphs, narratives, adapters and incremental updates remain its project
knowledge store. This work improves task compilation, delivery and reuse; it does not create a
remote model's KV cache locally or claim complete semantic understanding of arbitrary projects.

## Delivered behavior

- Noun-first change requests retain their leading operation/shape instead of ranking later
  acceptance constraints equally with it.
- AST-verified Python dictionary producers outrank consumers/logging dictionaries when a
  request explicitly describes an output shape. Matching small contracts and bounded literal
  frontend constructors are included. Dynamic/spread cases still need normal type checks.
- Class scalar settings are exact edit units, avoiding entire class bodies.
- Unrelated tests are filtered from ordinary edit candidates; target-related tests remain
  available through graph/source/package evidence.
- Source is deduplicated between primary and supporting-definition passes. Final delivered
  ranges alone enter session memory; partial packets reserve recovery instructions.
- Native MCP task output defaults to CLI-equivalent compact text. `format="json"` explicitly
  preserves structured packets; errors preserve structured detail and set the protocol flag.
- Explicit MCP `session` / PRISM_SESSION interoperates with CLI/hooks across reconnects,
  invalidating only ranges whose file hashes changed.
- Bounded local task-packet caches avoid repeated retrieval computation. Source/artifact/stat
  revisions guard the key; delivered source is hash-verified before a cache hit is returned.
- `prism knowledge` and full-profile `prism_knowledge` provide a budgeted local inventory.
- Existing prompt hooks can inject evidence before the model's first turn; the shipped skill
  documents using it once and sharing session IDs. Existing native installers are reused.

## Verification

- Full offline Python suite: **357 passed** after compiler, constructors and transport changes.
- Final cache-hardening regression run: **84 passed**, covering the changed engine, hooks,
  freshness, session invalidation and CLI/MCP parity.
- Ruff lint and formatting passed; strict mypy passed; Git whitespace check passed.
- Network-blocking fixtures were active. Windows asyncio tests ran in the native runtime:
  the restricted subprocess runtime blocked its loopback self-pipe. Tests used an isolated
  writable temp root outside this repository to avoid inheriting its .aicontext directory.
- No viewer/UI code changed. No hosted CI, release publishing, or dependency installation ran.

## Frozen-source retrieval diagnostic

Same original Platforma snapshot, same two requests, same 2,000-token estimated budget:

| Task | Previous packet | Final packet | Reduction | Initial edit evidence |
|---|---:|---:|---:|---|
| Code expiry | 1,974 | 1,515 | 23.3% | sufficient |
| KPI field | 1,940 | 736 | 62.1% | sufficient |

These are `ceil(chars/4)` packet estimates, not provider token usage. KPI evidence includes
the backend builder, frontend Kpi contract and an affected literal snapshot construction.
The expiry packet includes the lifetime setting, issue/email evidence and exhaustive matching
locations. Common-number matches still require judging which belong to the requested behavior.

## Fresh agent pilot

Six fresh agents, two real edits, baseline / CLI / MCP, same inherited gpt-6.1-sol model and
medium effort. Single-phase discovery + editing + isolated verification; normal baseline
targeted search, without a forced repository dump. The MCP client uses the real unmodified
stdio server, compact output and no model-facing schema dump; it is still a client adapter,
so native host schema-injection overhead is not isolated.

The live pilot ran before the final construction-candidate and preserved-timestamp cache
hardening refinements. Those final changes were tested deterministically and are not included
in an invented live-agent savings claim. This campaign's single-phase design differs from the
earlier two-phase benchmark: compare arms within this table, not totals across campaigns.

| Metric across two edits | Without | CLI | MCP |
|---|---:|---:|---:|
| Processed input | 435,341 | 495,542 (+13.8%) | 385,941 (-11.3%) |
| Generated output | 3,206 | 4,840 (+51.0%) | 3,188 (-0.6%) |
| Cache-weighted input proxy | 76,838 | 72,067 (-6.2%) | 55,548 (-27.7%) |
| Model turns | 12 | 15 (+25.0%) | 12 (+0.0%) |
| Tool output, chars/4 estimate | 16,424 | 8,382 (-49.0%) | 5,779 (-64.8%) |

All arms passed **18/18** frozen plus additional behavior/type-presence assertions. The original frozen assertions are 14/14 per arm.

Each MCP agent made one prism_task call. All agents updated the backend builder, frontend Kpi
type and its affected literal snapshot construction. Python syntax/isolated behavior checks
passed. Full frontend type checking was unavailable in the dependency-free trial copies.

CLI still used more processed input. Its trace includes redundant reads, a malformed search
command retried in a later turn, and an unavailable TypeScript probe; these consumed tokens
and were retained. Context retrieval alone does not control an agent's verification strategy.
MCP improved on these matched tasks, but two tasks with one repetition cannot demonstrate a
large general saving or statistical non-inferiority. There was no human blind scoring or
full-study power analysis. No session was dropped for poor performance.

Cache-weighted proxy = uncached input + 0.1 × cached input, not an invoice. Model input includes
cached input once. Parent implementation/orchestration, diagnostics and harness verification
are excluded from agent totals. Output is separate.

## Artifacts and product usage

- [Usage and architecture](context-engine.md)
- [CLI reference](cli.md)
- [Measured agent results](context-engine-validation-2026-10-08.json)
- Raw transcripts, protocol traffic and frozen-source before/after packets:
  `D:/Projects/prism/.benchmark-runs/context-engine-2026-10-07/`.

Core remains offline and never edits user source. All agent edit trials were in isolated copies.
No main-repository commit or release was made. Existing unrelated untracked user files remain.

The major next acceptance step is a varied, repeated native-host benchmark with explicit
correctness/type checks. The specification's 70% orientation-saving target and every roadmap
performance/accuracy/UI acceptance criterion remain unproven; “full project” does not justify
declaring those targets complete without evidence.
