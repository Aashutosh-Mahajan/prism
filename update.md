# PRISM — Update Plan

> Status: Phase 7 build validated; owner-authorized ArogyaTrack Codex Luna benchmark completed · Updated 10 October 2026 · Owner: AlgoSmiths
> Inputs: the Antigravity/ArogyaTrack benchmark (runs 1–6, 56 sessions), `docs/final-report-2026-10-10-v2.md`, `docs/improvement-plan-2026-10-10.md`, and a survey of other token-saving tools.

This plan fixes what the benchmarks exposed. It has three aims:

1. **CLI and MCP must give the same result.** They share one engine, so any gap between them is a delivery defect or measurement noise.
2. **Raise the measured saving** from about 53–57% of total tokens (30–34% of fresh tokens) toward the 70–75% target, by addressing the actual cost drivers.
3. **Prove the result honestly**: several hosts, several repositories, repeated runs, confidence intervals.

Every item must respect `CLAUDE.md`: local and offline, no API keys, a deterministic index, opt-in per user, never modify user source code, and a token budget on every output surface. Items that come close to one of these rules are marked **⚠ Principle check**.

---

## Progress (updated 10 October 2026)

The implementation is built and tested. The owner-authorized Claude Round 3 design has now run on ArogyaTrack with Codex `gpt-6-luna`: 60 sandboxed sessions, four tasks, five setups, three repetitions. [Results and limitations](docs/benchmarks/phase7/codex-luna-arogya-2026-10-10.md). The broader three-repository proof campaign remains separate.

| Item | State | Notes |
|---|---|---|
| 1.1 One renderer | done | CLI and MCP share `render_task`; `tests/integration/test_surface_parity.py` asserts equal text on 10 queries, hook body equality, and shared session memory. It found and fixed a real defect: blocks of one packet marked each other "shown earlier" when a session was active. |
| 1.2 Shared session memory | done | `session_id(explicit, root)` falls back to the session the prompt hook last served, so a tool call after the hook gets references, not a second copy. |
| 1.3 Lean MCP | done | Default profile is `prism_task` only; `standard` adds status/context/impact; `full` unchanged. Test caps schema + instructions at 330 tokens (measured about 200). |
| 1.4 Warm process | done | `prism/navigator/daemon.py`, ADR 0003. Local pipe/socket with a random key, started by a `prism task` call only in an enabled repo, idle exit 10 min, stopped on pause/disable/uninstall, falls back to in-process with identical output. `prism/taskfast.py` answers from it without loading typer. Warm end-to-end about 0.55–0.75 s (was 1.1–1.3 s); the 200 ms target is **not** met (Python start-up about 0.2 s plus retrieval about 0.3 s). |
| 1.5 Hooks everywhere | partial | Antigravity: `PreInvocation` packet + `Stop` verify gate. Other hosts' hooks already existed. |
| 1.6 `doctor --session` | done | Records hook and tool deliveries in the work log; reports why PRISM was or was not used. |
| 2.1 Stop signal | built as a correctness gate | `prism hook stop`: if a value change still leaves the old value, the agent is sent back once with the remaining lines; silent otherwise. Protects success; does not by itself cut tokens. |
| 2.2 Test selection | done | Packets print `Run: <exact command with the listed test files>` from the detected toolchain (pytest, jest/vitest, go; others print the plain command). |
| 2.3 Edit-ready packets | improved | Literal lines grouped per file; a complete list may take up to 80% of the budget before occurrences are dropped; JSON measured compact. Age task at 1200 tokens: 11 of 18 sites → all 18, exhaustive. |
| 2.4 Scope statement | exists | |
| 2.5 Guidance wording | done | Instruction block about 230 → about 120 tokens. |
| 3.1 Cache-stable text | done | Header is constant; a test forbids digits, paths and time in it. |
| 3.2 Output filtering | done | `prism filter -- <cmd>` (ADR 0004). Built as an explicit wrapper, not an auto-rewriting hook, because Claude Code's rewrite mechanism skips the permission prompt. |
| 3.3 Packet compaction | partly done | per-file grouping of literals. |
| 4.1 Languages | done | Dart, Kotlin, Swift via a dependency-free declaration scanner (`prism/parsing/braces.py`): classes, functions, methods, doc comments, bases, imports, calls, complexity. ArogyaTrack now indexes 38 Dart, 4 Kotlin, 6 Swift files (399 → 440 files, 1712 → 2070 symbols). Not a full grammar. |
| 4.2 Semantic search | unchanged | Already optional via the `[semantic]` extra; no model available to measure the recall gain here. |
| 4.3 Ranking feedback | done | `prism/navigator/feedback.py`, ADR 0005; bounded, decaying, switchable. |
| 4.4 Latency | partly | One directory walk per query, cached stemming and tokenization, warm process, a memoised file-stat check inside it, and a repair of the packet cache (packets quoting text/data files were never served): a repeated request on a warm index takes about 0.04 s server-side. End to end a warm `prism task` is 0.5–0.8 s on this machine, of which Python start-up and imports are about 0.4 s; the 200 ms target is not reachable for a per-call process. The resident MCP server has no start-up cost. |
| 5 Benchmark | runner ready, **not run** | `run_agy.py` runs arms in parallel (`--parallel N`, `--reps N`) with a private agent home and MCP config per session; `compare4.py` shows live means. Waiting for your go-ahead and the three repositories. |
| 6 Docs/hygiene | mostly | `docs/cli.md`, `docs/configuration.md` and ADRs updated; reliability matrix and CHANGELOG still to refresh. |

---

## 0. Where we are

| Measure | Current value |
|---|---|
| CLI + hook, runs 5+6 pooled | −30.2% fresh / −53.1% total |
| MCP + hook, run 6 only (pooled against both baselines) | −27.4% / −49.9% (−33.9% / −57.1%) |
| Best single task | −83% total (age rule, run 5) |
| Weakest hook session | −28% total (run 6) |
| Variation between runs, same setup | 65% vs 37% |
| Variation in the baseline between days | ±40% |
| Warm CLI query latency | ~1.3 s (target 200 ms) |
| Hosts benchmarked | Antigravity only (`gemini-3.8-flash-medium`) |
| Repositories benchmarked | 1 (ArogyaTrack) |
| Repetitions per cell | 1 |

### 0.1 Why the CLI and MCP numbers differ

Both arms call `prism.navigator.api.op_task`, so they find the same things. The differences come from:

| # | Cause | Mechanism | Effect |
|---|---|---|---|
| D1 | **Noise** (single runs) | The winner flips: run 3 CLI −52% vs MCP −33%; run 4 CLI −1% vs MCP −37%; run 6 CLI+hook −37% vs MCP+hook −50% | A gap that changes sign carries no information |
| D2 | **Adoption** | The CLI depends on the agent remembering a shell command; one CLI session made 0 Prism calls. MCP tools sit in the tool list. | A whole session can run as the baseline |
| D3 | **Per-call schema cost** | MCP tool schemas are re-sent on every model call, even in the lean 4-tool profile | Grows with the number of turns |
| D4 | **"Already sent" memory differs** | The CLI keeps it on disk per `--session`; MCP keeps it in server memory. A missing session key means full code is re-sent. | Repeated code in one arm, references in the other |
| D5 | **Output framing differs** | CLI prints text; MCP returns JSON plus a text copy | Different size, and agents trust each differently |
| D6 | **Latency differs** | CLI does a cold-ish start and a tree check per call (~1.3 s); the MCP server is warm | Agents switch to grep when a tool is slow |
| D7 | **Arm setup differs** | MCP edits `~/.gemini/config/mcp_config.json`; the CLI needs a PATH shim. Early runs also used different prompts. | Confounded comparisons (fixed for runs 5–6) |

D2–D6 are fixed in Phase 1. D1 is fixed in Phase 5.

### 0.2 Where the remaining tokens go

Total tokens ≈ number of model calls × context per call.

- **Context per call:** the host's fixed prompt (17–30k tokens on Antigravity) dominates. Prism cannot shrink it, but it can avoid adding to it and can keep its own text cache-friendly.
- **Number of calls:** in the weakest session the packet was complete, yet the agent re-opened the same files and ran about 25 extra searches (mobile app, i18n scripts, test discovery). This is the largest lever left.
- **Tool output:** test runs, git and build output are not touched by Prism today.

---

## Phase 1 — CLI/MCP parity and adoption (days 1–4)

**Goal:** CLI, MCP and hooks deliver byte-identical packets with the same memory and speed, and Prism gets used in every session where it is enabled.

### 1.1 One delivery renderer
- **What:** one function, e.g. `prism/navigator/deliver.py::deliver(pack, surface)`, that produces the final text for every surface. MCP returns the same text as its single `content` item, with structured fields only where a caller asks for them.
- **Where:** `navigator/task_pack.py` (`render_task`), `mcp/server.py`, `cli.py` (`task` command), `hooks/prompt.py`, `hooks/antigravity.py`.
- **How:** move all formatting into `deliver`. Each surface only wraps it (a hook header, a JSON envelope for `--json`).
- **Acceptance:** a new `tests/integration/test_surface_parity.py` runs 30 fixed queries on the medium fixture and asserts the CLI text, MCP text and hook packet (minus header) are byte-equal.

### 1.2 Shared session memory
- **What:** a single disk-backed "already sent" store used by the CLI, MCP and hooks.
- **Where:** `navigator/session.py` (already two-phase `load_seen`/`save_seen`), `mcp/server.py` (drop the in-memory-only path).
- **How:** derive the session key from the host session ID: the hook payload `session_id`/`conversationId`, MCP client info, or the `PRISM_SESSION` environment variable. Fall back to a key per process start, so a missing key never means "send everything again".
- **Acceptance:** for the same query repeated in one session, every surface returns a reference instead of code. A test covers each surface.

### 1.3 Lean MCP surface
- **What:** the default profile exposes just `prism_task`, plus `prism_status` for consent reporting. Descriptions are cut to the minimum.
- **Where:** `mcp/server.py` (profile table), skill text, `docs/cli.md`.
- **How:** move `prism_context`/`prism_impact` behind `--profile standard`. Measure the serialized schema size in a test.
- **Acceptance:** the default schema is ≤ 150 tokens (chars/4), enforced by a budget test.

### 1.4 Warm query process for the CLI
- **What:** `prism task` hands the query to a resident local process when one is running and starts one on demand. The process holds the index, caches and session memory.
- **Where:** new `prism/navigator/daemon.py`; `cli.py` (client path); `navigator/freshness.py`.
- **How:** use a stdio-spawned child that listens on a per-repo named pipe (Windows) or Unix socket in `.aicontext/cache/`. It never opens a TCP port, exits after 10 minutes idle, and runs only in enabled, unpaused repos. If no process is reachable, it falls back to the in-process path.
- **⚠ Principle check:** "no background activity in repos the user hasn't chosen" and "no network listener". The process is local IPC only, starts only after a query in an enabled repo, and is idle-killed. Record this as an ADR in `docs/adr/` before building.
- **Acceptance:** warm `prism task` p95 < 200 ms on the medium fixture and < 400 ms on ArogyaTrack, measured by `tests/benchmarks/`. Consent tests show no process is ever started in a repo that is not enabled.

### 1.5 Hooks by default on every host that supports them
- **What:** `prism init` offers the prompt hook (default yes) for Claude Code, Codex, Gemini CLI and Antigravity.
- **Where:** `integrations/{claude_code,codex,gemini,antigravity}.py`.
- **How:** re-check each host's current hook format against its documentation (Antigravity's `PreInvocation` → `injectSteps.userMessage` is already verified). Keep the instruction block as a fallback.
- **Acceptance:** installer snapshot tests; running `init` twice is a no-op; uninstall restores backups.

### 1.6 Adoption diagnostics
- **What:** `prism doctor --session <id>` reports whether the hook fired, whether the rules/skill were loaded, how many Prism calls the session made, and why there were none.
- **Where:** `maintenance.py` (`doctor`); hook events in `writers/worklog.py`.
- **Acceptance:** in a fixture with the hook removed, `doctor` reports "hook not firing" and names the config file to check.

**Phase 1 exit gate:**
- The parity test is green.
- The MCP schema is ≤ 150 tokens.
- CLI p95 < 200 ms on the medium fixture.
- A two-repetition smoke benchmark (baseline / CLI+hook / MCP+hook, 4 tasks) shows a CLI–MCP difference within the noise band of the baseline repetitions.

---

## Phase 2 — Cut the number of model calls (week 1–2)

**Goal:** remove the extra exploration agents still do after a complete packet. This is the biggest remaining saving.

### 2.1 Stop signal after edits
- **What:** after the agent edits, a hook runs `prism task --mode verify` for the original request. If every listed site has been changed and no other occurrences remain, it injects a short "All N sites changed; run: <tests>; nothing else matches" message.
- **Where:** `hooks/` (post-edit, plus Stop/PostInvocation for hosts that have one), `navigator/api.py` (verify mode already exists).
- **How:** verify runs only against changed files plus postings, so it stays within the post-edit time budget. It says nothing if the result is uncertain.
- **Acceptance:** in a fixture session simulation, the message is produced after the final edit and not before. The benchmark shows fewer model calls after the edit (tracked metric: calls after the last edit).

### 2.2 Exact test selection
- **What:** packets include "Run: `<command>`" with the specific related test files or IDs (from `tests_map`, call-graph reach and literal hits), using the detected toolchain command.
- **Where:** `extractors/tests_map`, `audit/toolchain_detect.py`, `navigator/task_pack.py`.
- **Acceptance:** on the seeded fixture, the listed tests include the test that fails for the seeded bug in ≥ 90% of cases.

### 2.3 Edit-ready change packets
- **What:** for change requests ("from X to Y", "add", "rename"), list every site as `file:line` with the exact current text and the scope of the change, and mark the list exhaustive when it is.
- **Where:** `navigator/request.py`, `navigator/literals.py`, `navigator/task_pack.py`.
- **Acceptance:** retrieval eval (`tests/benchmarks/retrieval_eval.py`): exhaustive-site recall ≥ 98% on the labelled cases. No case is marked exhaustive while missing a site.

### 2.4 Scope statement that agents trust
- **What:** one line saying what was searched (code, text/data files, file count) and what was deliberately skipped (vendored code, generated files, binaries), so the agent does not re-check those areas.
- **Where:** `navigator/task_pack.py` (already partly present).
- **Acceptance:** present in every packet with a literal list. Budget test still passes.

### 2.5 Stronger skill and instruction guidance
- **What:** tighter wording in `templates/skills/prism-context/SKILL.md` and the instruction blocks: "An exhaustive list is complete; do not re-grep. Do not open files that are not listed unless an edit fails."
- **Acceptance:** the skill consistency test passes, and the text is ≤ 120 tokens.

**Phase 2 exit gate:** in the smoke benchmark, average model calls per edit task fall ≥ 25% against the end of Phase 1, with no loss in task success.

---

## Phase 3 — Cut tokens per call (week 2)

**Goal:** make each call cheaper, both in Prism's own text and in noisy tool output.

### 3.1 Cache-friendly injected text
- **What:** the hook header and fixed instruction text stay byte-identical across requests, with the variable packet last, so the provider's prompt cache keeps hitting.
- **Where:** `hooks/prompt.py` (`HEADER`), `hooks/antigravity.py`.
- **Acceptance:** a unit test confirms the header has no timestamps, counters or paths. The benchmark reports the cache-read share per arm.

### 3.2 Output filtering for noisy commands (opt-in)
- **What:** an optional hook that compresses test, lint, git and build output: keep failures, summaries and the first error with its location; save the full output to `.aicontext/cache/tee/` for the agent to read on demand.
- **Where:** new `prism/hooks/output_filter.py`; installed by `prism init` only if the user accepts it (default off at first).
- **⚠ Principle check:** this changes what the agent sees from its own commands, not source code. It must be opt-in, reversible, and never drop a failure line. Record an ADR.
- **Acceptance:**
  - Golden tests on pytest, jest, flutter test, git log/diff and npm build output, with every failure line kept.
  - Benchmark: tool-output tokens fall ≥ 50% on tasks that run tests.

### 3.3 Packet compaction
- **What:** remove repeated paths (group lines under a file header), shorten JSON keys in the text form, and drop empty sections.
- **Where:** `navigator/task_pack.py`, `deliver.py`.
- **Acceptance:** the same information in ≥ 15% fewer tokens on the retrieval eval set. Golden files updated.

### 3.4 Stale-packet guidance
- **What:** for hosts that support context editing or tool-result clearing, the skill tells the agent that earlier Prism packets can be dropped after an edit. There is no code change in Prism.
- **Acceptance:** documented per host in `docs/integrations.md`.

**Phase 3 exit gate:** average fresh input tokens per call drop ≥ 10% against the end of Phase 2. With 3.2 enabled, tool-output tokens drop ≥ 50%.

---

## Phase 4 — Retrieval quality and speed (weeks 2–3)

**Goal:** fewer missed sites, so agents have no reason to search themselves, and every language in a repository is covered.

### 4.1 Language depth
- **What:** tree-sitter symbol, call and import parsing for Dart, Kotlin and Swift, with Java gaps closed.
- **Where:** `parsing/treesitter.py`, `graph/call_graph.py`.
- **Acceptance:** fixture repos per language; symbol extraction golden files; ArogyaTrack's Flutter app has a call graph.

### 4.2 Semantic search when available
- **What:** when the `[semantic]` extra is installed, `prism task` blends embedding scores with BM25 and literals. When it is not installed, behaviour is unchanged.
- **Where:** `navigator/semantic.py`, `navigator/request.py`.
- **Acceptance:** top-3 block recall on vague requests improves ≥ 10 points on the retrieval eval, with no regression on exact requests. The no-network test passes with a local model.

### 4.3 Local ranking feedback
- **What:** record which listed sites the agent actually edited (from the post-edit hook) and boost similar symbols and files for later requests in that repo.
- **Where:** `writers/worklog.py`, `navigator/request.py`.
- **How:** a deterministic boost table in `.aicontext/cache/` (gitignored), with no learning outside the repo. Index determinism is unaffected because the table is cache, not an index artifact.
- **Acceptance:** replaying a week of work logs on the fixture improves top-1 accuracy, and disabling the table restores the old behaviour exactly.

### 4.4 Query latency
- **What:** prebuilt postings for the text corpus, incremental corpus updates, manifest stat caching, and avoiding JSON reloads per query (helped by 1.4).
- **Where:** `navigator/source_index.py`, `navigator/textcorpus.py`, `navigator/freshness.py`, `navigator/cache_db.py`.
- **Acceptance:** query p95 < 200 ms on a generated 100k-LOC repo (CI benchmark job). Update ≤ 0.5 s per file still holds.

**Phase 4 exit gate:** retrieval eval targets met; latency targets met; the full test suite, reliability matrix and incremental-equivalence tests are green.

---

## Phase 5 — Proof: a real, repeated benchmark (weeks 3–4)

**Goal:** a result that can be quoted, including the CLI–MCP comparison.

### 5.1 Hosts
Claude Code, Codex, Gemini CLI and Antigravity. Each uses its native hook and MCP integration installed by `prism init`, with no special prompts.

### 5.2 Arms per host
`baseline` (no Prism), `cli+hook`, `mcp+hook`, and, for one host only, `cli` and `mcp` without hooks, to measure the hook's share.

### 5.3 Repositories and tasks
- 3 repositories: ArogyaTrack (Python/Flutter), one TypeScript web app, and one Java or Go service, each pinned to a commit.
- 8–10 tasks per repository: orientation, single-site change, multi-site value change, new field across layers, bug fix with a failing test, and rename.
- Each task has a hidden checker in the style of the existing `hidden/` tests.

### 5.4 Protocol
- 3 repetitions per cell, in a randomized order.
- A fresh sandbox per session, deleted after scoring (as in the current `run_agy.py`).
- Baseline and treatment run in the same time window, to control day-to-day drift.
- Record fresh, cache-read and output tokens, model calls, tool calls, Prism calls, wall time, success, and provider cost (cache reads at the provider's rate).

### 5.5 Analysis
- Extend `analysis/bench_analysis` to report per-cell mean, median and 95% bootstrap intervals; a paired comparison per task; and the CLI–MCP difference with its interval.
- Report success separately. A saving with a lower success rate is reported as such.

### 5.6 Acceptance gates
- CLI and MCP differ by ≤ 10 points with intervals overlapping, or the report explains the remaining difference.
- The average total-token saving is reported with its interval. The report says plainly whether 70–75% is reached.
- No arm loses more than 5 points of success against the baseline.

### 5.7 Budget and approval
Present the frozen campaign (hosts, models, task list, number of sessions, estimated tokens and cost) for approval **before** any paid run, as the benchmark kit requires.

---

## Phase 6 — Product hygiene and documentation (ongoing, finish by week 4)

1. **Docs:**
   - "When Prism helps and when it doesn't": small single-file tasks may not benefit, and graph metadata can exceed a tiny change.
   - The per-host integration matrix.
   - The CLI vs MCP choice guide.
2. **ADRs:** warm query process (1.4), output filtering (3.2), ranking feedback (4.3).
3. **Schemas:** any packet or cache change is versioned. `prism migrate` handles cache formats, and the skills are updated.
4. **CI gates:** ruff, mypy, the full pytest suite, the reliability matrix (95+ cases), the parity test, budget tests, the no-network test and latency benchmarks.
5. **Reports:** update `docs/phase-status.md` and replace `docs/final-report-2026-10-10-v2.md` with the Phase 5 report.
6. **Release:** CHANGELOG entry, version bump, and a clean `prism init` on a fresh machine for each host.

---

## Phase 7 — From the research and the 3-host results (planned, not started)

Basis: `docs/research-token-efficiency-2026-10-10.md` and the round-3 benchmark (3 hosts × 3 repetitions).
Cost ≈ model calls × context per call; PRISM so far removes search calls but not the edit/read/check calls.

| # | Item | Why | Acceptance |
|---|---|---|---|
| 7.1 | **Twin definitions**: group functions with the same normalised body across files; the packet says "same function in N files: change all N" | 21 of the 22 failing WEBP sessions edited one copy and missed the other | WEBP task passes in ≥ 80% of sessions on every host |
| 7.2 | **De-noise packets**: down-rank `archive/`, vendored and out-of-scope areas (frontend when the request says backend) | wasted packet budget, wrong files read | irrelevant-block share ≤ 10% on the labelled retrieval set |
| 7.3 | **Batching line**: packets end with "read the N listed files in one turn; edit them in one turn" | ~20 tool calls in ~18–25 model calls today | model calls per edit session −20% on Claude Code and Antigravity |
| 7.4 | **`prism diff`**: for mechanical old→new changes, print a unified diff the agent applies with one `git apply` (text only; PRISM never edits code) | edits are 5–10 calls and Claude Code needs Read before Edit | age task ≤ 8 model calls; tests still pass |
| 7.5 | **`prism find`**: several patterns/globs in one call, grouped and budgeted | replaces 3–8 sequential searches | search calls per session −40% when the packet is insufficient |
| 7.6 | **Read-range hints** in packets (`Read(file, offset, limit)`), after a test of what Claude Code accepts as "read before edit" | whole large files (e.g. 1,700-line locale JSON) enter context and are re-sent every call | no whole-file reads of files > 800 lines |
| 7.7 | **Smaller standing context**: install only `prism-context` by default; deliver packets as clearable tool results where the host clears old results | PRISM's own text is re-sent on every call (~60k tokens/session measured) | first-call context +≤ 2k tokens over baseline |
| 7.8 | **Verify gate for Claude Code (`Stop`) and Codex** | protects pass rate; only Antigravity has it | no setup passes fewer sessions than no Prism |
| 7.9 | **Benchmark the steps**: 3 hosts × 3 repetitions × 3 repositories (the two other repositories still to be supplied) | single repo, single task set | per-step change reported with spread |
| 7.10 | **Acceptance line** at the end of each packet: "done when `verify` shows no remaining sites and these tests pass" | a fuller task specification lowered spend ~30% ([arXiv 2608.25399](https://arxiv.org/abs/2608.25399)) | fewer post-edit exploration calls (calls after last edit −20%) |
| 7.11 | **Staleness guard**: `prism doctor` flags a managed block or brief older than the running engine; never generate narrative by default | a stale context file costs more than none ([arXiv 2608.16630](https://arxiv.org/html/2608.16630v1)) | doctor reports it; block kept ≤ 120 tokens |
| 7.12 | **Test weighting**: rank tests by call-graph distance, never return an empty list, warn when a selector would run zero tests | testmon-style silent no-selection; TDAD weighted impact | seeded fixture: the failing test is in the list ≥ 90% |
| 7.13 | **Opt-in `prism hook dedupe-read`** (Claude Code PreToolUse, deny-only with a steering hint, 20-minute expiry, kill switch) | agents re-read; enforcement beats prose | repeated-read calls −50% with no pass-rate loss |
| 7.14 | **`--detail brief|full`** packets; `git apply --check` on every printed diff | concise/detailed responses; SWE-agent guardrails | brief ≈ 40% smaller; no unappliable diff printed |
| 7.15 | **Semantic channel evaluation** on vague requests and an overview packet confident enough for the hook to speak on "explain the architecture" | Cursor +12.5%; Cody −35% retrieval failures; our hook is silent there | top-3 recall +10 points; hook speaks on ≥ 80% of overview requests |
| 7.16 | **Docs only**: Explore-on-cheap-model, Codex `model_reasoning_effort` / `model_verbosity`, Gemini CLI caching needs an API key, compaction breaks the cache | host settings PRISM cannot change | `docs/integrations.md` updated |
| 7.17 | **Benchmark rigor**: ≥ 5 repetitions, tokens per solved task, pass^k, bootstrap intervals, a Java/Go and a TypeScript repository | 30× run variance; ~9 runs for a 2-point effect | report states interval per setup |

Deep-dive sources and the list of techniques *not* to adopt: `docs/research-deep-dive-2026-10-10.md`.

Honest ceiling: ~21k tokens of fixed context per call means ≥ 4–6 calls even for a perfect edit, so about −60–75% on Claude
edit tasks if 7.3 and 7.4 work, about −45–55% on Codex, and small one-site tasks cannot reach 70% on any host.

---

## Phase 7 — build status (10 October 2026)

Implementation status is recorded below. Offline semantic retrieval and the owner-authorized
[60-session ArogyaTrack Codex Luna campaign](docs/benchmarks/phase7/codex-luna-arogya-2026-10-10.md)
are complete. Validation and the remaining broader host-dependent gates are tracked in
[the Phase 7 report](docs/phase7-validation-2026-10-10.md).

| # | Item | State | Notes |
|---|---|---|---|
| 7.1 | Twin definitions | built | `enrich.find_twins`: same name and signature with bodies ≥ 65% alike (≥ 80% otherwise); generic names and names defined in > 6 places ignored. Needed a relaxed threshold: the real WEBP pair is 79% alike. |
| 7.2 | De-noise | built | archive/vendor demoted (×0.3); the other monorepo area (×0.5) only when the request says "backend", "frontend" or "mobile" (the words "server" and "api" are ignored: a failing test showed they describe behaviour, not scope). Related blocks that would not fit give way to a twin line. |
| 7.3 | Batch line | built | "the N files above are independent; read together, edit together". |
| 7.4 | `prism diff` / Patch | built | byte-exact (CRLF, no-final-newline), `git apply --check` before offering, applied with `git -c core.autocrlf=false apply`; none unless the list is exhaustive and current. On the real age task: 18 sites in 10 files. |
| 7.5 | `prism find` | built | CLI and MCP (`prism_find`); also fixed click expanding `*` on Windows. |
| 7.6 | Read ranges | built | offset/limit windows for files over 600 lines. Whether Claude Code accepts a partial read as "read before edit" is untested. |
| 7.7 | Smaller standing context | partly | only `prism-context` installed by default (`--all-skills`); instruction block ~140 tokens (CLI) / ~170 (MCP). Delivering packets as clearable tool results: not built (no host API; documented). |
| 7.8 | Verify gate | built | shared `hooks/gate.py` for Claude Code and Codex; Codex's blocking Stop decision verified on 0.162. |
| 7.9 | Benchmark the steps | tooling ready | not run (awaiting go-ahead and the two other repositories) |
| 7.10 | Done-when line | built | |
| 7.11 | Stale block warning | built | `prism doctor` |
| 7.12 | Test weighting and fallback | built | bounded breadth-first caller traversal (3 hops, 64 symbols), then name/import matches and nearest indexed tests, including unmapped tests. Missing tests are disclosed. Seeded regression coverage exists; the >=90% external-effectiveness gate remains unmeasured. |
| 7.13 | `dedupe-read` | built, opt-in | deny-only PreToolUse; companion PostToolUse records confirmed returned lines only, SessionStart resets after compaction/resume. Failed reads never poison coverage. `prism init --dedupe-reads` |
| 7.14 | `--detail brief` | built | ≤ 800 tokens, sites and tests only |
| 7.15 | Overview prompts and semantic evaluation | built and locally evaluated | installed MiniLM: 8 paraphrases, top-three source recall 62.5% -> 75%, complete packet coverage 62.5% -> 87.5%. Offline retrieval only; see `docs/phase7-validation-2026-10-10.md`. |
| 7.16 | Host settings docs | built | `docs/agents.md` |
| 7.17 | Benchmark rigor | built, diagnostic analyzer hardened | external runner overrides remain; shipped `tests/benchmarks/agent_stats.py` resamples tasks and matched repetitions, rejects missing cells, counts failure costs and output tokens. Confirmation analysis still follows the frozen protocol. |

---

## Timeline summary

| Phase | Duration | Main outcome |
|---|---|---|
| 1. Parity & adoption | days 1–4 | CLI = MCP output, shared memory, ≤ 150-token MCP schema, < 200 ms CLI, hooks everywhere |
| 2. Fewer model calls | weeks 1–2 | Stop signal, exact tests, edit-ready packets: ≥ 25% fewer calls |
| 3. Cheaper calls | week 2 | Cache-stable text, opt-in output filtering, compact packets |
| 4. Retrieval & speed | weeks 2–3 | Dart/Kotlin/Swift, optional semantic search, ranking feedback, latency targets |
| 5. Proof | weeks 3–4 | 4 hosts × 3 repos × ~30 tasks × 3 reps, with intervals |
| 6. Hygiene | ongoing | Docs, ADRs, CI gates, release |

## Risks

| Risk | Mitigation |
|---|---|
| Host hook formats change | Keep formats only in `integrations/<agent>/`; snapshot tests; check each host's docs at release |
| Output filtering hides a needed line | Opt-in; never drop failure lines; tee file always written |
| Warm process seen as background activity | ADR; only in enabled repos; idle-exit; local IPC only; `prism pause` stops it |
| Agents still explore despite complete packets | Measure calls after the packet; the stop signal; report it honestly rather than over-claim |
| Benchmark cost | Frozen campaign and approval before paid runs; smoke runs on 4 tasks first |
| 70–75% not reached | Report the measured value with intervals; do not promise a percentage |
