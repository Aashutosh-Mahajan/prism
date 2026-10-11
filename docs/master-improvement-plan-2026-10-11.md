# PRISM master improvement plan — token efficiency (11 October 2026)

**Audience:** Claude Code, working in this repository. Written to be executed task by task.
**Supersedes:** [`token-efficiency-plan-2026-10-11.md`](archive/token-efficiency-plan-2026-10-11.md) (same day, audit-only). That file stays as the audit record; this one adds a survey of real-world tools, a comparison with PRISM, and every earlier recommendation reconciled with the current code.
**Builds on:** [`research-token-efficiency-2026-10-10.md`](archive/research-token-efficiency-2026-10-10.md), [`research-deep-dive-2026-10-10.md`](archive/research-deep-dive-2026-10-10.md), [`improvement-plan-2026-10-10.md`](archive/improvement-plan-2026-10-10.md), [`trust-and-token-fixes-2026-10-10.md`](archive/trust-and-token-fixes-2026-10-10.md), [`final-report-2026-10-10-v2.md`](archive/final-report-2026-10-10-v2.md), [`phase-status.md`](phase-status.md), [`../update.md`](../update.md).
**Status:** proposal. Nothing here is implemented. Measurements are from a scratch copy of the source on 10 October 2026, not from live agent runs.

---

## 0. How to use this file

Read sections 4.1 and 4.2 first for what PRISM saves and which setup to default to. Then paste the kickoff prompt from section 9 into Claude Code. It tells Claude Code to read this file, re-measure the baseline (task T00) before changing anything, and then work through the tasks in section 6 in order, one commit per task, stopping at each phase gate.

Rules for whoever executes it:
1. **Verify before building.** Several earlier recommendations may already be done (section 7). If a task's behaviour already exists, close the task with a note instead of rewriting it.
2. **Measure before and after.** Every task that changes packet content must be checked with the replay and packet-audit scripts (T00). A change that lowers file recall by more than 2 points is reverted or reworked.
3. **Stay inside the project's principles** (section 1). If a task seems to need a network call, an LLM, or edits to user source code, stop and flag it. Do not work around it.
4. **Numbers in this file are labelled.** "Measured" means I ran it. "Reported" means a source claims it. "Estimate" means my arithmetic. Do not treat reported or estimated numbers as acceptance results.

---

## 1. Constraints Claude Code must respect

From `CLAUDE.md` (sections 3, 4, 16, 17, 20) and the conventions seen in the code and tests.

**Principles (non-negotiable):**
- PRISM never calls an LLM, never needs an API key, and the core makes no network calls. Reasoning work is delegated to the host agent through skills and tools.
- The index is deterministic: same code in, same `.aicontext/` bytes out.
- Updates are incremental (one file, under 0.5 s); queries stay under 200 ms p95 as a target.
- Retrieval over dumping: every output surface has a token budget, and no feature may make the agent read more by default.
- PRISM never modifies user source code. It may write patches under `.aicontext/cache/patches/` for the user or agent to apply.
- Opt-in per project and per user. Hooks and MCP do nothing in a repository the user has not enabled. Agents must never run `prism init`, `prism scan`, `prism enable` or `prism install --global` on their own.

**Engineering conventions:**
- `ruff check .`, `python -m mypy .` (strict) and `python -m pytest -q` must pass. Viewer: `cd viewer && npm run test` and `npm run typecheck`.
- Only `writers/` writes into `.aicontext/` (plus `audit/record.py` and `narrator/refresh_commit.py` through writer helpers).
- CLI and MCP are thin wrappers over the same library functions. Never implement logic in both, and never in the viewer API.
- Anything that ends up in an agent's context is a token budget: concise, no decoration.
- Schema changes need a version bump, a migration, and updates to skills and schema tests. Skill files are tested: every `prism` command, flag and JSON field a `SKILL.md` mentions must exist.
- Installers are idempotent and reversible; running `init` twice is a no-op; uninstall restores backups.
- The packet cache key includes an engine fingerprint (see `trust-and-token-fixes`, item 8), so packet changes do not serve stale cached answers. Keep it that way.
- The suite runs with sockets blocked. Any script that needs the network (for example token calibration) lives under `tests/benchmarks/`, is not collected by pytest, and is run by hand.
- Windows is the owner's main platform: keep path handling, line endings (`\r\n`), quoting and Git Bash behaviour in mind. Do not assume POSIX.
- Commit style in this repository: `type(scope): summary` (for example `fix(mcp): ...`, `refactor(navigator): ...`, `docs: ...`).

**Commands:** lint `ruff check .`; types `python -m mypy .`; tests `python -m pytest -q`; viewer `cd viewer && npm run test`.

---

## 2. What real-world token saving looks like in October 2026

The ten ways people save tokens with coding agents, with the evidence behind each. "Reported" figures come from the tool's own documentation or a single write-up unless stated.

| # | Approach | Where the tokens are saved | Evidence and its quality | Needs a model or network? |
|---|---|---|---|---|
| 1 | **Platform features**: prompt caching, context editing (clear stale tool results), MCP tool search (deferred tool definitions), skills (description only until used) | Cached reads cost 0.05× input on Sonnet 5.5 and Opus 5.5 (0.025× on Fable 5.1); stale tool output cleared; unused schemas not loaded | Official docs; context editing reported −84% on an internal 100-turn test | Host-side |
| 2 | **Lean standing context**: `CLAUDE.md` under 200 lines, path-scoped rules, nested `CLAUDE.md` loaded on demand | Standing context is re-sent every call; imports do not reduce it | Official Claude Code docs | No |
| 3 | **Repository maps**: Aider's tree-sitter map ranked by PageRank (default 1,024 tokens; 512 for small projects, 2–4k for large); Repomix `--compress` (signatures only) | A bounded map instead of whole files | Aider docs give budgets; Repomix publishes no reduction figure | No |
| 4 | **Code-graph / symbol-index servers**: CodeGraph, GitNexus, Graphify, jCodeMunch, Codebase-Memory | Graph queries and symbol-level fetch instead of reading files | CodeGraph reported −62% tokens on average over 7 repositories (one question, 4 runs; agent held ~80% more retrieval context at the end); Graphify reported 71.5× on a 52-file corpus but ~1× on 6 files; jCodeMunch reported 28.3× against "open the top 3 files"; Codebase-Memory reported ~10× fewer tokens but answer quality 83% vs 92% | Mostly no; Graphify uses a model for docs and images |
| 5 | **Semantic search**: Cursor, Sourcegraph Cody (BM25 + embeddings), Claude Context | Better first hit means fewer exploration turns | Cursor +12.5% accuracy; Cody −35% retrieval failures; Claude Context −39.4% tokens at equal F1 0.40 on 30 SWE-bench Verified tasks, one small model | Embeddings; Claude Context needs a vector store |
| 6 | **Agentic search subagents** (SWE-grep, WarpGrep) and cheaper-model exploration (Explore subagent on Haiku) | Fewer main-context turns; cheaper tokens | Vendor claims (about 10× faster; 3.8 vs 12.4 steps) | Yes (trained models) |
| 7 | **Language servers**: Claude Code's LSP tool; Serena | Exact definitions and references instead of grep | One benchmark: −31–33% tool-output tokens, every reference found where grep missed some (9 of 11; 249 of 260) | No (a language server per language) |
| 8 | **Shell-output filtering**: RTK (hook rewrites Bash commands), Headroom (proxy, reversible compression), context-mode (sandboxed execution, only stdout enters context) | Test, build and log output is the biggest single source of junk tokens | RTK reported 60–99% on bash output by family; context-mode reported 98% (315 KB → 5.4 KB) and Headroom reported 47–92% by workload; all self-reported, shell output only, bytes/4 | RTK: no. Headroom: optional local models. context-mode: no |
| 9 | **Session memory**: claude-mem (3-layer search → timeline → fetch, 50–100 / 100–200 / 500–1,000 tokens per layer), Mem0, Cline Memory Bank, Anthropic memory tool, context-mode's post-compaction "session guide" | Do not re-derive what the last session learned | Mem0 reported ~6.9k vs 25k+ tokens per query on LoCoMo (vendor); claude-mem reported ~10×; Cline reported "up to 40%"; none independently measured | claude-mem and Mem0 use an LLM to compress |
| 10 | **Obsidian / "LLM wiki"**: a vault of linked Markdown notes with a schema file (`CLAUDE.md`), an index and a log; the agent ingests, queries and lints it | Open only the notes a question needs | Author estimate 30–50k vs 70–80k tokens per session (~40%), no method given | The agent maintains the wiki (LLM) |

Also seen, with weak or no token evidence: caveman-style terse-output skills (measured output reduction 12–23%, not the 65–75% advertised; one analysis puts output at 0.6–2.5% of a typical Claude Code bill), model-based code compression (LongCodeZip 4.3–5.6× on code completion; needs a model for scoring), Windsurf Codemaps (LLM-generated maps, no token claim), and test-impact selection (TDAD, pytest-testmon).

### What the survey says, in five points
1. **The standing and tool-output costs are the cheap wins.** Lean `CLAUDE.md`, deferred tools, and filtered shell output are what most popular tools actually deliver. Retrieval quality comes second.
2. **Hooks beat instructions.** context-mode reports instruction files alone reach about 60% of its saving versus about 98% with hooks (vendor claim). PRISM's own benchmark agrees: only the hook setup changed behaviour reliably.
3. **Graph tools trade accuracy for tokens unless something checks the result.** Codebase-Memory's 83% vs 92% and CodeGraph's 80% larger end-of-session retrieval context are the warnings. PRISM's verify mode and exhaustive-literal lists are its answer; keep reporting pass rate beside tokens.
4. **Always-loaded memory goes stale and costs every turn.** Cline's Memory Bank loads five files each session; Graphify and the LLM-wiki pattern both need maintenance. The independent two-agent study found context files did not change pass rates. Keep anything like this on-demand, and label what was inferred (Graphify tags each edge `EXTRACTED`, `INFERRED` or `AMBIGUOUS`).
5. **Obsidian setups save tokens through structure, not magic:** a short schema file, an index, links and frontmatter so the agent opens few notes. They fail when notes are orphaned or stale. PRISM already exports an Obsidian vault; its module summaries are the wiki layer, and 56 of 72 in this repository are still placeholders (section 3).

---

## 3. Where PRISM stands against that field

Legend: ✓ present, ◐ partial or opt-in, ✗ missing. "Not seen" means none of the tools I read described it.

| Capability | PRISM today | Closest real-world tool | Verdict |
|---|---|---|---|
| Local deterministic index, no model, no network | ✓ | Aider map, Repomix, CodeGraph | At par, stricter than most |
| One-call task packet: matching code, callers, tests, impact | ✓ (`prism task`) | CodeGraph `codegraph_explore`, GitNexus `context` | At par |
| Exhaustive exact-match lists and a verify pass | ✓ | Not seen | Strength |
| Checked patch for rename and value changes | ✓ (`Patch:`, `prism diff`), but breaks above 40 sites | Not seen; GitNexus and Serena rename through tools/LSP | Strength with a defect (task T10) |
| Packet precision | ◐: measured token precision 37% in replay | Aider budgets 512–1,024 tokens | Improve (T11–T15) |
| Hook-delivered context | ✓ (Claude Code, Codex, Gemini CLI, Antigravity, Cursor) | claude-mem, context-mode | At par |
| Shell-output filtering | ◐: `prism filter` exists but the agent must choose to prefix it | RTK (automatic rewrite), context-mode, Headroom | **Gap** (T20, T21) |
| Reversible / queryable saved output | ◐: full output saved to a tee file with a path | Headroom CCR, RTK `recall`, context-mode FTS5 | Gap (T21) |
| Edge confidence on the call graph | ✗ | Graphify `EXTRACTED/INFERRED/AMBIGUOUS`, LARGER edge confidence | Gap (T16) |
| Exact references from a language server | ✗ (static graph only) | Claude Code LSP, Serena | Complement, do not build (T44) |
| Impact of the current uncommitted diff | ◐: `impact <symbol>` exists, no "my diff" mode | GitNexus `detect_changes` | Gap (T28) |
| Clusters and flows precomputed | ◐: clusters in the viewer; flows in overview packets | GitNexus Leiden clusters and processes | Adequate |
| Session memory and recovery after compaction | ◐: work log, `prism recall`, session-start summary ≤ 140 tokens; "already sent" ranges may not reset on compaction | claude-mem, context-mode session guide | Verify and fix (T25) |
| Layered recall (index → detail) | ◐: unverified | claude-mem 3 layers | Check (T25) |
| Obsidian export | ✓ (`prism graph export --obsidian`) | Graphify `obsidian/`, LLM-wiki setups | At par; add an index note (T29) |
| Narrative "wiki" layer | ◐: module summaries are agent-written on request; 56 of 72 unwritten placeholders here | LLM wiki, Windsurf Codemaps | Keep on-demand; never inject placeholders (T30) |
| Cost warning in context ("full suite takes 14 min") | ✗ | Only helpful content in the two-agent study | Add (T26) |
| Lean standing context in the install | ◐: ~600 tokens, but five copies of the same rules, 4.3 KB skill | Skills progressive disclosure | Improve (T22–T24) |
| Lean standing context in this repository | ✗: `CLAUDE.md` 68 KB ≈ 17k est. tokens | Docs: under 200 lines | **Do first** (T03) |
| Semantic retrieval | ◐ opt-in, MiniLM on NumPy, top-3 recall 62.5% → 75% on 8 paraphrases | Cursor, Cody, Claude Context | Evaluate code-specific models (T42) |
| Injection hardening of injected snippets | ◐: 220-character cap only | Codex hardening guidance | Add (T27) |
| Cost-weighted, repeated, per-task-type benchmark | ◐: single runs, token totals | HAL-style pass^k and cost | Improve (T01, T40, T41) |

**What PRISM does that the surveyed tools did not describe:** exhaustive exact-match lists with an "edit-ready" verdict, checked patches, a verify mode, twin-definition warnings, consent per user per repository, and a strict no-model core. Protect these.

---

## 4. Cost model (use it, do not assume it)

Prices from the Anthropic pricing and prompt-caching pages, 11 October 2026.

| | Sonnet 5.5 | Opus 5.5 | Fable 5.1 | Haiku 5.5 (≤100k prompt) |
|---|---|---|---|---|
| Input per M tokens | $2 | $4 | $10 | $0.10 |
| Output per M tokens | $10 | $20 | $50 | $0.50 |
| Cache write 5 min / 1 h | 1.25× / 2× | 1.25× / 2× | 1.25× / 2× | 1.25× / 2× |
| Cache read | 0.05× | 0.05× | 0.025× | 0.1× |

- Output is 5× input. The cache lifetime is 5 minutes by default and is refreshed on each read. Prompts under 512 tokens are not cached on the 5.5 models.
- Models from 4.7 on use a tokenizer giving roughly 30% more tokens for the same text than Sonnet 4.6 and earlier. PRISM's chars/4 estimate predates this and has never been calibrated (T02).
- `improvement-plan-2026-10-10.md` item 19 assumes a 0.1× cache read. Use the per-model table above (T01).
- **Which part of the bill dominates is not settled.** One analysis puts output at 0.6–2.5% of a typical Claude Code bill; my arithmetic for a 25-call Sonnet 5.5 session gives output a larger share than that, because new context (cache writes) is the biggest term. Do not argue it: T01 makes the benchmark report the split from real usage logs.
- Arithmetic example (estimate): a 1,400 est.-token packet injected on call 1 of a 20-call session costs about $0.0035 to write and $0.0027 to re-read, about $0.006. The packet is cheap in money; its cost is mostly latency and context quality. Avoided turns, avoided tool-result tokens and avoided cold-cache rewrites are where the money is. A 17k-token standing file costs about $0.04 for every cold-cache rewrite.

### 4.1 What PRISM saves today, and what to expect after this plan

Measured in this project's own benchmarks (`docs/final-report-2026-10-10-v2.md`, `docs/benchmarks/phase7/codex-luna-arogya-2026-10-10.md`). Negative means fewer tokens than no PRISM. "Total" includes cached input; "fresh" is uncached input.

| Benchmark | Setup | Total tokens | Fresh input | Passed |
|---|---|---:|---:|---|
| Claude, runs 5 and 6 pooled | installed + hook | −53% (−57% against both baselines) | −30% | see report |
| Codex `gpt-6-luna`, ArogyaTrack, 60 sessions | hook | −33% | −15.5% | 12/12 (baseline 10/12) |
| same | MCP + hook | −39% | −28% | 11/12 |
| same | MCP only | −11.5% | −20% | 12/12 |
| same | CLI only | **+28%** | +6% | 10/12 |

Read these with care: the same hook setup saved 65% in one Claude run and 37% in another, and the Codex 95% interval for the hook setup runs from −63% to +13%. The 70–75% target was not reached on average.

**Projection after the plan (an estimate, not a measurement):** a further 10–20% off what PRISM still spends, which moves the Claude hook result from about −53% to about −58…−62% total and from −30% to about −37…−44% fresh, and the Codex hook result from about −33% to about −40…−46%. Test-heavy and rename-heavy work could gain more if T20 works; small single-file edits will gain about nothing. Most session tokens are cheap cache reads, so the dollar saving is smaller than the token saving (T01 reports both). Quote "about 55% today, aiming for about 60%". Do not quote 70%. Only T41 can confirm it.

### 4.2 Delivery setups: what each is, why they differ, what to keep

| Setup | How the agent gets PRISM | Who decides |
|---|---|---|
| CLI | agent runs `prism task "…"` in a shell | the agent |
| MCP | `prism_task` tool in the agent's tool list | the agent |
| Hook | host runs PRISM when the prompt is submitted and adds the packet to context | PRISM, automatically |
| MCP + hook | hook gives the first packet, tool answers follow-ups | both |

Why they differ: in the Codex run the hook delivered the packet in 100% of hook sessions and 0% of the others, so the agent started knowing where to look. CLI-only cost more than no PRISM, most likely because the agent skipped it or ran it on top of normal exploring (not traced session by session). MCP adds its tool description to every turn, and the agent must choose to call it. MCP + hook had the lowest tokens but one failed session.

**Decision recorded in this plan (owner's call, 11 October 2026):**
- Keep all of them in the code. The hook and the MCP server both run on the CLI, so removing any saves nothing now.
- **Default install: hook only** on hosts that support hooks (Claude Code, Codex, Antigravity), once T22 confirms hook-only is as good as hook + MCP.
- **MCP is opt-in** (`--mcp`). Use it for hosts with no hooks (lean profile there) and for agents that need follow-up lookups.
- **Never recommend CLI-only.** Keep the CLI as the engine, for humans, scripts and CI.
- Keep the dedupe-read, stop and post-edit hooks as they are (opt-in, cheap).
- Do not change any default until T22 has produced its numbers.

### 4.3 Reducing benchmark noise

**Why it matters.** The same hook setup saved 65% in one Claude run and 37% in another, and the Codex hook interval runs from −63% to +13% on 12 task-sessions per setup (4 tasks × 3 repetitions). With that much noise a 5–10 point improvement cannot be seen, so every claim in this plan would stay unproven.

**How much data is needed (rough).** Half the interval width is about 38 points at 12 pairs. Interval width shrinks with the square root of the sample, so for the same spread: ±20 points needs about 45 pairs, ±15 about 80, ±10 about 170. The 4 × 3 design is too small by a factor of 4–10. This assumes the spread stays the same and is only a planning figure; T41 re-estimates it from the pilot.

**Where the noise comes from, and the fix for each**

| Source | Fix |
|---|---|
| Too few sessions, too few tasks | 30 or more tasks (mixed types), 3 repetitions each, rather than 4 tasks. More tasks reduce noise more than more repetitions of the same task, because tasks differ more than runs do |
| Tasks differ hugely in size, so the average is dominated by a few | Compare per task on a log scale (ratio of PRISM to baseline for the same task), then average the log ratios. Report the median ratio beside the mean |
| Agents take different paths on the same task | Pair every PRISM run with a baseline run of the same task and repetition, in the same time window; randomise arm order; analyse paired differences only |
| Cache state changes the bill (cache hits depend on the 5-minute lifetime and on six sessions running at once) | Record tokens by class (fresh, cache write, cache read, output) and compute cost from a fixed price table (T01), not from whatever the cache did that run. Run arms interleaved, not one arm after another |
| Model, effort or tool versions change mid-campaign | Pin model, effort, host version and PRISM commit; write them in the result file; abort a campaign that sees a version change |
| Infrastructure failures (sandbox, denied tool calls) | Keep excluding them from effect estimates, but report how many there were per arm |
| Scoring noise (keyword heuristic for orientation) | Use hidden tests wherever possible; for orientation tasks use a fixed rubric with at least two reviewers, or drop them from the headline |
| Large run-to-run differences in the baseline itself | Use the task's baseline usage from earlier runs as a covariate (the CUPED idea): subtracting the part of a run's usage that the baseline already predicts removes shared variation |
| Heavy-tailed token counts | Use trimmed means or medians next to means; report the bootstrap interval, never a single point |

**Noise-free evidence in between.** Changes to packet selection, layout and size (T10–T16) can be judged offline without any agent: replay precision and recall (T00), the packet audit (T00) and the retrieval scorer (T40) are deterministic. Use these as the gate for Phase 1 and spend the live budget only on questions the offline numbers cannot answer (does the agent behave differently, does it still pass).

**Decision rules, fixed before the run.** Write the success threshold and the interval rule into `docs/benchmarks/protocol.md` before starting: for example, adopt a change only if the paired 95% interval for total cost is entirely below zero and pass rate does not fall; otherwise report "not shown". Stop the campaign at the planned sample size; do not stop early on a good-looking result.

---

## 5. Audit findings this plan rests on (measured, 10 October 2026)

Scratch copy of the source, 229 files indexed, no agent involved, chars/4 estimates.

| ID | Finding |
|---|---|
| M1 | 10 requests gave packets of 4.4k–7.1k characters (1.1k–1.8k est. tokens); at least two printed 2000/2000 |
| M2 | Composition of the 10 packets (61.7k chars): source code 67.4%, callers 6.3%, candidate headers 4.6%, test code 2.0% (18% in the rename packet), next/batch lines 2.4% |
| M3 | Replay of 38 focused commits (subject as query, HEAD index): file recall 62%, any-hit 82%, **token precision 37%**, mean packet 1,406 est. tokens. A rough proxy |
| M4 | "make the hook skip prompts shorter than 6 words" returned a 79-line `user_prompt` body (~900 est. tokens); `MIN_WORDS` (`prism/hooks/prompt.py:21`) landed in "Missing source" |
| M5 | Rename with 7 sites → `Patch:` line, 3.6k chars. `estimate_tokens` (80 word hits) → no patch, 4.2k chars. `render_task` (31 hits) → no patch, 6.7k chars, cause not found. `MAX_NAMED_LINES = 40` in `prism/navigator/literals.py` explains the first |
| M6 | 45% of caller characters are test files (they repeat the `Tests:` line); 31% are dotted qualified names that repeat the path |
| M7 | In code blocks, per-line number prefixes are 9.7% of characters and docstring/comment-start lines 10.4% |
| M8 | Installed fixed overhead is small (MCP schema ~250 est. tokens; instructions 234 chars; SessionStart 430 chars; `CLAUDE.md` block 739 chars; skill 4,260 bytes) |
| M9 | This repository's `CLAUDE.md` is 68,361 bytes; sections 12, 11, 8, 9 are 8.3, 7.7, 7.6, 5.8 KB; section 19 still lists phases 0–5 as future work |
| M10 | `source-v2.sqlite` (3.3 MB) remains beside `source-v3.sqlite`; 56 of 72 `.aicontext/modules/*.md` are unwritten placeholders |

---

## 6. Tasks

Priority: P0 first, P1 next, P2 later. Effort: S under a day, M a few days, L a week or more. Every task ends with its acceptance line; do not mark it done until that passes. Paths are relative to the repository root and were checked against the source on 10 October 2026; if one has moved, find it with `prism locate` and say so in the commit message.

### Phase 0 — baseline and quick wins (days 1–2)

#### T00 — Baseline harness (P0, M)
**Goal.** Numbers to compare every later change against.
**Where.** New `tests/benchmarks/replay_precision.py`, `tests/benchmarks/packet_audit.py`, `tests/benchmarks/packet_audit_requests.json` (the 10 requests in Appendix A), `tests/unit/test_replay_parsers.py`. Reuse the in-process helpers that `tests/unit/test_enrich.py` and `tests/benchmarks/run.py` use to index a directory and call `prism.navigator.api.op_task` without touching user consent state.
**Steps.**
1. `packet_audit.py`: for each request run `op_task` at budget 2000; record characters, est. tokens, and the share of source code, test code, callers, candidate headers, next/batch lines, and per-line-number prefix characters (the M2/M6/M7 measures). Write JSON to `output/benchmarks/` (gitignored).
2. `replay_precision.py`: for the last N non-merge commits that change 1–4 Python files under `prism/` (skip subjects starting `docs|chore|ci|test`), use the subject without its `type(scope):` prefix as the query. **Index the parent commit** (a temporary `git worktree` of `<sha>^`), not HEAD. Report file recall, any-hit rate, token precision (code tokens in changed files over all code tokens), block-level recall (changed hunks inside delivered blocks), mean packet est. tokens. The script in Appendix B is a working HEAD-only starting point.
3. Run both; commit the summary numbers to `docs/benchmarks/replay-baseline-2026-10-11.md`.
**Accept.** Both scripts run offline in under 10 minutes for 40 commits; the unit test parses a canned packet; baseline file committed. Expect numbers near M1–M3 but not identical (parent-commit indexing).

#### T01 — Cost-weighted benchmark metrics (P0, S)
**Goal.** Replace "total tokens" as the headline with a per-model cost and a breakdown.
**Where.** `tests/benchmarks/tokens.py`, `agent_stats.py`, `agent_report.py`, new `tests/benchmarks/pricing.json` (with a `retrieved` date and the section 4 table), `tests/unit/test_agent_stats.py`.
**Steps.** Report per cell: new-context tokens (uncached input plus cache writes), cache reads, output tokens, model turns, dollars from `pricing.json`, tokens per solved task, pass@1 and pass^k. Unknown models fall back to 0.1× cache read and are flagged in the output. Show the dollar split by token class. Also compute a "fixed-cache" cost from the token classes and the price table, so cache timing differences between runs do not change the headline (section 4.3).
**Accept.** Re-running the 10 October benchmark data through the new report gives the same pass counts and a dollar column; unit tests cover each pricing branch and the fallback.

#### T02 — Calibrate the token estimator (P0, S)
**Goal.** Know how far chars/4 is from real counts on current models.
**Where.** New `tests/benchmarks/calibrate_tokens.py` (manual run, network and API key allowed because it is not part of the suite and not part of `prism/`); `prism/core/tokens.py`; `[tool.prism] token_scale` in `prism/config.py`.
**Steps.** Take 50 packets from T00 grouped as code-heavy, prose-heavy, digit/JSON-heavy; count each with Anthropic's token-counting endpoint for each supported model family; write ratios to `docs/benchmarks/token-calibration.json`. Add an optional `token_scale` (default 1.0) applied inside `estimate_tokens`; keep the function pure and deterministic.
**Accept.** Report committed; default behaviour and every existing budget test unchanged. Changing the default scale is an owner decision (section 11).

#### T03 — Cut this repository's own standing context (P0, S)
**Goal.** `CLAUDE.md` from about 17k est. tokens to 4k or less.
**Where.** `CLAUDE.md`; new `docs/spec/`; nested `prism/navigator/CLAUDE.md`, `prism/integrations/CLAUDE.md`, `viewer/CLAUDE.md`; new `tests/unit/test_docs_budget.py`.
**Why.** Claude Code's docs: target under 200 lines; `@path` imports load at launch and do not reduce cost; nested `CLAUDE.md` files load only when files under that directory are used; the project-root file is re-read after compaction.
**Steps.**
1. Keep a core of about 150 lines: sections 1–4 condensed, section 6 as one paragraph, 15 (layout), 16 (conventions), 17 (testing, short), 20 (checklist). Leave the `prism-managed` block intact.
2. Move sections 7–14 and 18 to `docs/spec/NN-name.md` verbatim (no content loss). Section 19 (roadmap) is stale: replace with a pointer to `docs/phase-status.md`. Sections 14 and 15 can be shortened because `prism` generates the same facts.
3. Put the parts relevant only to one area in a nested `CLAUDE.md` of at most 120 lines (navigator budgets and packet rules; integration/consent rules; viewer stack). **Do not use `.claude/rules/`**: `.gitignore` ignores `.claude/`, so the rules would not be committed. If you prefer path-scoped rules, add `!/.claude/rules/` to `.gitignore` deliberately.
4. Search tests and docs for references to `CLAUDE.md` section numbers and fix them.
**Accept.** `tests/unit/test_docs_budget.py` asserts root `CLAUDE.md` ≤ 200 lines and each nested file ≤ 120, and that every `docs/spec/*.md` is linked from the root file. Manual check: `/context` in Claude Code shows project memory ≤ 4k est. tokens and no startup length warning.

#### T04 — Respect the hook size cap (P0, S)
**Goal.** Never let a hook string exceed Claude Code's 10,000-character limit (above it the text is saved to a file and the model sees a path plus the first 2,000 characters).
**Where.** `prism/hooks/prompt.py` (`PROMPT_BUDGET`, the `prompt_budget` clamp near line 209), `prism/hooks/formats.py` (`render_context`), `prism/cli.py` (`doctor`), `tests/integration/test_prompt_hook.py`.
**Steps.** For the Claude Code format cap the rendered context at 9,500 characters by re-running retrieval at a lower budget (never cutting mid-line). Keep the 128–8000 config range but warn in `doctor` when `prompt_budget × 4` exceeds the cap. Record the decision, and the decision not to depend on `updatedToolOutput` (reported ignored for built-in tools in several versions), in a new `docs/adr/0006-hook-output-contract.md`. Use `additionalContext` and plain stdout only.
**Accept.** Test with a request that would produce more than 10,000 characters: output is under the cap and still ends with its `Next:` line. `doctor` prints the warning for `prompt_budget = 6000`.

#### T05 — Say why there is no patch (P0, S)
**Goal.** Every refused patch carries a reason; find out why `render_task` (31 hits) gets none.
**Where.** `prism/navigator/enrich.py` (`build_patch`, `parse_replacements`), `prism/navigator/patchcmd.py`, the `Patch:` rendering in `prism/navigator/task_pack.py`, `tests/unit/test_enrich.py`.
**Steps.** `build_patch` currently returns `None` for six different reasons. Return a reason code instead (`no_replacement`, `conflicting_destinations`, `not_exhaustive`, `new_name_exists`, `line_changed`, `git_rejected`, plus `too_many_sites` and `generic_name` from T10). When the request parses as a mechanical change and no patch is offered, print one line: `Patch: none (<reason>)`. `prism diff` prints the same reason. Reproduce the `render_task` case with a fixture and fix or explain it.
**Accept.** Each reason has a test. `prism task "rename render_task to render_packet everywhere"` either yields a patch or names a real conflict.

### Phase 1 — packet precision and mechanical changes (week 1)

#### T10 — Remove the 40-site cliff (P0, M)
**Goal.** A rename with 80 hits returns a checked patch and a packet of about 400 est. tokens or less.
**Where.** `prism/navigator/literals.py` (`MAX_NAMED_LINES = 40` used at lines ~469–528, `MAX_OCCURRENCES_SCANNED = 200`, `MAX_FILES_PER_LITERAL = 80`), `prism/navigator/enrich.py` (`build_patch` requires `lit.complete`), `prism/navigator/task_pack.py` (`LITERAL_SHARE`, literal rendering, `render_task`), `tests/unit/test_enrich.py`.
**Steps.**
1. Detect a mechanical request early with `parse_replacements(query)` and pass `mechanical=True` into literal collection. Then use `MECHANICAL_NAMED_LINES = 400`, raise the scan and per-file caps to match (the scan cap must be at least the line limit), and keep the default 40 for everything else.
2. Refuse (`too_many_sites`) above 400, and (`generic_name`) for identifiers of three characters or fewer or in a short stoplist (`get`, `set`, `run`, `id`, `data`…), so a rename of a common word never produces a sprawling patch.
3. When the list is complete and a patch exists, render the sites grouped by file with line numbers but no line text, and suppress source blocks for sites the patch covers. Keep the definition, the `Patch:` line, the tests and the `Next:` line.
**Accept.** Fixture with 80 sites over 12 files: packet contains a `Patch:` line that passes `git apply --check`, ≤ 400 est. tokens. 450 sites → `Patch: none (too_many_sites)`. `estimate_tokens` in this repository behaves the same way. Incremental-equivalence and determinism tests unaffected (query-time change only).

#### T11 — Tighter block selection (P0, M)
**Goal.** Higher token precision at equal recall.
**Where.** `prism/navigator/task_pack.py`: constants at the top (`MIN_RELATIVE_SCORE`, `TIGHT_RELATIVE_SCORE`, `MAX_BLOCKS`, `TIGHT_MAX_BLOCKS`), `_select` (~line 1269), `_fit_blocks` (~1320), and the existing `tight` argument.
**Steps.**
1. Find where `_select(..., tight=True)` is requested and extend the condition to: intent `edit` and confidence `high`, or the request names the symbol or file outright.
2. In tight mode use floor 0.5 and at most 3 blocks (already defined).
3. Replace greedy fill in `_fit_blocks` with a deterministic 0/1 knapsack: maximise summed block score under the remaining token budget, subject to `MAX_BLOCKS` and `MAX_PER_FILE`. With at most about a dozen candidates, exhaustive search or a small DP is enough. Break ties by (−score, file, start line).
**Accept.** Replay (T00): token precision ≥ 55%, file recall within 2 points of baseline, mean packet ≤ 1,000 est. tokens. Unit tests for the selector on synthetic blocks; golden packets updated deliberately in the same commit.
**Risk.** Lower recall on vague requests: wide profile stays for medium or low confidence.

#### T12 — Excerpts centred on the match (P0, M)
**Goal.** Show where the request points, not the head of the function.
**Where.** `prism/navigator/task_pack.py`: `_windows` (~308), `_group_blocks` (~320), `_partial_block` (~1424), `_render_source` (~367), `WHOLE_SYMBOL_MAX` uses at ~355, 1139, 1186, 1241.
**Steps.** The top block keeps whole-symbol rendering up to 120 lines. Every other block over 40 lines renders its signature plus windows (pad 3) around lines that match query terms, literals or edit anchors, merged with the existing gap rule, marked as an excerpt. `read_next` lists only ranges that contain no match. A symbol or constant the request names must never appear only under "Missing source".
**Accept.** Reproduce M4 in a fixture (constant defined outside the named function): its line is in the packet. On the 10 audit requests every request-matched line appears. Packet token precision does not fall.

#### T13 — Tests are listed, not shown (P0, S)
**Where.** `prism/navigator/task_pack.py`: `TEST_DEMOTION`, `_related_tests` (~1456), `_nearest_tests`, `_links` (~1528, `MAX_CALLERS`, `MAX_TESTS`).
**Steps.** Exclude test files from candidate source blocks unless the request contains a test word (`test`, `tests`, `pytest`, `spec`, `coverage`) or names a test file or symbol. Drop test callers from "Callers" when the `Tests:` line is present. Cap tests at 2.
**Accept.** Test-file share of packet characters ≤ 3% on non-test requests (M2: up to 18% before). A request that asks about a test still gets the test source.

#### T14 — Format compaction (P1, S)
**Where.** `prism/navigator/task_pack.py` (`render_task`, `_render_source`, `_snippet`), `prism/navigator/overview.py`, `tests/integration/test_surface_parity.py`, golden tests.
**Steps.**
1. Number only the first line of a source block and the first line of each excerpt segment, with `⋮ N lines omitted` between segments; keep full numbering for literal-list lines and "Missing source" ranges. The header already carries the range.
2. Callers: drop the dotted qualified name where it repeats the path; group by file (`prism/hooks/entry.py: run_hook :91`).
3. Strip docstring bodies in non-primary Python blocks.
**Accept.** ≥ 12% fewer characters at equal located content; CLI, MCP and hook output remain byte-identical (the parity test); `--json` form carries the same data.
**Risk.** Agent behaviour with unnumbered lines: check with one live pilot before this ships as default (T41).

#### T15 — Adaptive budget everywhere (P1, M)
**Where.** `prism/hooks/prompt.py` (`_retrieve` ladder, `INITIAL_PACKET_BUDGET`), `prism/navigator/api.py` (`op_task`), `prism/cli.py` (`task`, default 2000 at ~line 601), `prism/mcp/server.py` (`prism_task`, 2000 at ~131 and ~381), `prism/taskfast.py` (line 18), `prism/navigator/daemon.py` (line ~210).
**Steps.** Move the hook's ladder (start at about 1,200, expand to the cap only if the packet is not sufficient and confidence is not low) into one library function used by CLI, MCP and the hook. Make the starting size depend on repository size (for example 800 under 500 symbols). An explicit `--budget N` stays exact. Edit-ready exhaustive results default to the brief detail level.
**Accept.** Mean packet ≤ 1,000 est. tokens on the audit set with no fall in the "sufficient" rate; parity test passes; default budget tests (≤ 2,000) pass.

#### T16 — Edge confidence on callers (P1, M; P2 for the persisted form)
**Goal.** Tell the agent which callers are certain and which are guesses, and send fewer guesses.
**Steps.**
1. *T16a, query time (S).* Label a caller `~` when its call resolves by bare name to more than one symbol or through an unresolved import. List resolved callers first, cap `~` callers at 3, and print one legend line only when a `~` is shown. No schema change.
2. *T16b, persisted (M, later).* Store `resolution` (`resolved`, `name`, `ambiguous`) per call edge in the call graph. This is a schema change: version bump, migration (`prism migrate`), schema files, skills, incremental-equivalence and golden tests (CLAUDE.md section 20.3).
**Where.** `prism/graph/`, `prism/navigator/store.py`, `prism/navigator/task_pack.py` (`_links`).
**Accept.** Callers section ≥ 40% shorter on the audit set; no loss of true callers against a grep oracle on this repository and one fixture; for T16b, `scan` ≡ `scan` + N×`update`.

### Phase 2 — shell output, standing context, memory and safety (weeks 2–3)

#### T20 — Make shell-output filtering automatic (P1, M, **has an open question**)
**Goal.** `prism filter` currently runs only when the agent chooses to call it. Field tools (RTK, Headroom, context-mode) get their savings by acting on every command. Reach the same effect without PRISM approving anything.
**Open question (do this first).** Claude Code's PreToolUse hook can return `updatedInput`. The documentation read on 11 October 2026 shows `updatedInput` directly under `hookSpecificOutput`, shows `permissionDecision` taking `allow`, `deny`, `ask` or `defer`, and says a silent exit 0 leaves the call to the normal permission flow. It does **not** clearly say whether `updatedInput` is applied when `permissionDecision` is absent. That part of the page was not read. Test it on the installed Claude Code version before writing any code: a throwaway hook that returns only `updatedInput` for a harmless `echo`, then check whether the command ran rewritten and whether the user was still prompted.
**Rule that does not change.** A PRISM hook must never return `permissionDecision: "allow"`. The dedupe hook is deny-only by design, and returning "allow" with a rewritten command could widen what the user has approved. Never rewrite a command that is not already allowed by the user's permission rules.
**Branch A — rewriting works without "allow" (and the user is still prompted when they would have been).**
1. New `prism/hooks/shellwrap.py` and a `pre-bash` hook subcommand in `prism/hooks/entry.py`. Only for single, simple commands whose first word is in `outputfilter.FAMILIES` (git, pytest, npm/pnpm, cargo, go, pip, ls/find/grep, docker…). Anything with `|`, `;`, `&&`, redirects, `$(`, backticks, heredocs or already starting with `prism` is left alone.
2. Rewrite to `prism filter -- <original command>` (check the real argument form in `prism/cli.py` and `prism/outputfilter.py`; keep the original exit code and keep stderr).
3. Install it through `ClaudeCodeIntegration.plan()` in `prism/integrations/claude_code.py` as an opt-in (`prism enable --shell-filter`), not part of the default hook set. The settings entry uses a matcher for the Bash tool and a short timeout.
4. A per-repo kill switch `[tool.prism] shell_filter = false` and an environment variable `PRISM_NO_FILTER=1`.
**Branch B — it does not work, or only works with "allow".** Do **not** ship a hook. Instead: document the pattern in `docs/` and the generated `CLAUDE.md` block (one line: "run long test, build and log commands as `prism filter -- <cmd>`"), and have `prism doctor` print a one-line suggestion with the measured saving from the user's own saved outputs. Record the finding in an ADR (`docs/adr/0007-shell-filter-hook.md`).
**Where else.** `prism/outputfilter.py` (`MIN_LINES = 60`, `FAMILIES`, tee directory), `tests/unit/test_output_filter.py`, `tests/integration/` for the hook.
**Accept (A).** On a corpus of at least 20 saved real outputs (pytest failures, npm install, git log, docker build) the filtered text is ≥ 70% smaller on average, 100% of failure lines, error lines and exit codes survive, and a failing command still fails. Unknown commands, pipelines and `prism …` commands pass through untouched. **Accept (B).** ADR committed; doctor line present; no hook added.

#### T21 — Queryable saved output (P1, S)
**Goal.** When `prism filter` trims output, the agent can get the rest cheaply without rerunning the command (the reversible-compression idea from Headroom, the sandbox idea from context-mode, kept local and simple).
**Where.** `prism/outputfilter.py` (tee under `.aicontext/cache/tee/`), `prism/cli.py` (`filter`), `prism/mcp/server.py` (optional `prism_filter_show`), `tests/unit/test_output_filter.py`.
**Steps.** Every trimmed output ends with `Full output: prism filter --show <id>`. Add `--show <id>`, `--grep <pattern>`, `--around <line> [-C N]`, `--tail N`, each with a character cap and a "truncated, use --around" footer. Ids are short and per-repo; the tee directory keeps at most N files or M bytes (T47 covers cleanup).
**Accept.** Round-trip test: filter a 3,000-line log, retrieve one error with `--grep`, get the surrounding lines with `--around`; the full text is recoverable byte for byte.

#### T22 — Make hook-only the default, with data (P1, S)
**Goal.** Ship the decision in section 4.2: hook-only default where hooks exist, MCP opt-in, CLI kept. MCP tool definitions cost standing context (deferred loading helps but does not remove it); hooks cost nothing until they fire.
**Where.** `prism/integrations/claude_code.py` (`plan()`), the Codex and Antigravity integrations, `prism/cli.py` (`init`, `enable`: the `--mcp` flag), `prism/mcp/server.py` (profiles lean/standard/full), `prism/doctor` output, docs.
**Steps.**
1. Using T01 metrics and the T41 protocol, compare three arms on the same tasks: hook only, MCP lean only, hook + MCP. Include the CLI-only arm once as a control.
2. If hook-only is within noise on pass rate and not more expensive, make it the default install on hosts with hooks. `--mcp` adds the server. On hosts without hook support the default is MCP with the lean profile.
3. Existing installs are not changed silently: `prism doctor` prints one line suggesting `prism enable --no-mcp` when the measured saving supports it.
4. Documentation says plainly that CLI-only is not recommended and shows the Codex numbers from section 4.1.
**Accept.** Decision and numbers recorded in `docs/benchmarks/`; install tests cover the new defaults per host; no default changes before the comparison has run.

#### T23 — Slim the skills (P1, S)
**Goal.** Skill descriptions sit in context every session (truncated at 1,536 characters each); skill bodies load only when used.
**Where.** `prism/integrations/` skill templates and generated `.claude/skills/*/SKILL.md`, `tests/integration/` for installed files.
**Steps.** Keep every description under about 300 characters and every `SKILL.md` under 500 lines. Add `disable-model-invocation: true` to workflow skills the user runs by name (this removes their description from context). Move the long `prism-context` text into a supporting file the skill links to. Keep only skills that the field data or benchmark justify.
**Accept.** `/context` shows skill listing ≤ 1k est. tokens for a PRISM-enabled repo; install and uninstall tests still pass; no skill file is written outside what `plan()` declares.

#### T24 — One source for instruction text (P1, S)
**Goal.** The MCP `INSTRUCTIONS`, the hook `HEADER`, the generated `CLAUDE.md` block and the skills say overlapping things in different words.
**Where.** `prism/mcp/server.py` (`INSTRUCTIONS`), `prism/hooks/prompt.py` (`HEADER`), `prism/hooks/formats.py`, `prism/integrations/*.py`, `prism/templates/` if present.
**Steps.** Define the rules once in a small module (for example `prism/instructions.py`) with a short form (about 60 words, used by the hook header and MCP) and a long form (used in the generated block). Each surface renders from it.
**Accept.** Surface parity test extended to compare the shared rules; total standing instruction text across hook + MCP + block falls by at least 30%.

#### T25 — Compaction safety (P1, S)
**Goal.** After Claude Code compacts, PRISM must not believe the agent still has code it no longer has.
**Where.** `prism/hooks/dedupe.py` (resets on compact already; 20-minute expiry), `prism/navigator/session.py` (`load_seen`, `save_seen`, `session_id`), `prism/hooks/entry.py`, `prism/integrations/claude_code.py` (SessionStart matcher is `startup|resume|clear|compact`).
**Steps.** On SessionStart with source `compact`, clear the seen ranges for the session and print the short orientation again. Confirm that the work log layer (`prism recall`) re-supplies what matters. Add a test that simulates compaction and checks that a range sent before it is sent again after it.
**Accept.** New integration test in `tests/integration/test_gate_dedupe.py`; manual check on a real compaction recorded in the PR.

#### T26 — Slow test suite warning (P1, S)
**Goal.** The one context item that helped in the two-agent ablation was a warning that the test suite is slow; give the agent that, only when true.
**Where.** `prism/hooks/prompt.py` or the packet footer in `task_pack.py`; timings from `prism/navigator/store.py` (record the duration of the last `prism verify`/test run) or a user-set `[tool.prism] slow_tests`.
**Steps.** If the last recorded full-suite run exceeded 120 seconds, or the setting is on, add one line to edit-intent packets: `Tests: full suite takes ~N min; run the named tests only`. Never add it otherwise.
**Accept.** Unit test for both branches; no extra line in the other case.

#### T27 — Treat injected snippets as untrusted (P1, M)
**Goal.** PRISM puts file text into the agent's context; a hostile file could carry instructions.
**Where.** `prism/navigator/task_pack.py` (`_render_source`, `_snippet`), `prism/hooks/formats.py`, `tests/unit/` new `test_snippet_sanitize.py`.
**Steps.** (1) Strip zero-width and bidirectional-control characters and other hidden Unicode from every rendered snippet. (2) Drop HTML comments from Markdown snippets, and do not render docs-only blocks from files named `AGENTS.md`, `CLAUDE.md`, `SKILL.md` or under `.claude/`/`.codex/` unless the request names them. (3) Wrap packet source in a clear delimiter and put one fixed line in the header saying that quoted code is data. (4) `doctor` flags hidden Unicode found in indexed files.
**Accept.** Fixture with a README holding an HTML-comment instruction and zero-width characters: the packet carries neither. Deterministic and byte-stable for clean files (no golden changes except the header line).

#### T28 — `prism impact --changed` (P1, M)
**Goal.** The analogue of GitNexus `detect_changes`: map the working-tree diff to affected symbols, callers and tests in one small answer, before a review or commit.
**Where.** `prism/cli.py` (`impact`), `prism/navigator/` (diff-to-symbol mapping already exists for `prism diff`; check `patchcmd.py` and `diffview` code), `tests/integration/`.
**Steps.** Parse `git diff -U0` (staged plus unstaged), map hunks to symbols using stored line ranges, expand one hop to callers and related tests with the existing `_links`, print grouped by risk (public symbol changed, many callers, no test). Honour a budget; `--json` supported. Read-only.
**Accept.** On the T00 scratch repository's synthetic commits the output names the changed symbols and at least the known callers; runs under 0.5 s warm.

#### T29 — Obsidian export upgrade (P2, S)
**Goal.** Match what the Obsidian/LLM-wiki practice gets right (short schema file, index, wikilinks, frontmatter) for people who browse the repository model in a vault.
**Where.** `prism/writers/obsidian.py`, `tests/unit/` for the writer.
**Steps.** Add an `index.md` with counts and links to cluster notes; cluster (module) notes listing members; consistent frontmatter (`type`, `path`, `kind`, `lines`, `callers`, `tests`) so Dataview queries work; a short `README` in the vault explaining the structure. Output must stay deterministic and sorted, with no timestamps.
**Accept.** Two exports of the same index are byte-identical; vault opens with working links; documented as a human view, not as agent context (the agent gets packets, not the vault).

#### T30 — Narrative policy (P2, S)
**Goal.** Never put "TODO" placeholder narratives in front of an agent; make filling them cheap.
**Where.** `prism/narrator/refresh.py`, `prism/writers/modules_md.py`, `prism/cli.py` (`refresh`, `doctor`).
**Steps.** Skip modules without a real summary in every agent-facing surface. `prism refresh --top N` selects the N highest-value modules (fan-in, recent change) for summarising by the agent and writes through the validator. `doctor` reports the fill ratio.
**Accept.** Placeholder text never appears in any packet (test over all surfaces). Doctor shows the ratio.

### Phase 3 — evidence, experiments and language coverage (weeks 4–6)

#### T40 — Offline retrieval scorer (P1, M)
**Goal.** Measure retrieval the way ContextBench does, without running agents.
**Where.** `tests/benchmarks/retrieval_*.py` (extend), new `tests/benchmarks/context_score.py`, `docs/benchmarks/`.
**Steps.** For each case with a known gold set (files, blocks, lines from T00 replay or SWE-style tasks), score file, block and line level recall, precision and F1, plus the share of delivered context the agent later used (from transcripts when available). Report beside the cost columns.
**Accept.** One command prints a table for the current commit; results stored per commit; a regression greater than the agreed margin fails a marker-gated test.

#### T41 — Live benchmark protocol that can show a difference (P1, M, costs money)
**Goal.** Stop drawing conclusions from single runs. Design the campaign so the interval is narrow enough to see a 10-point difference (section 4.3).
**Where.** `tests/benchmarks/agent_*.py`, `docs/benchmarks/protocol.md`, `docs/benchmarks/campaign-template.md`.
**Steps.**
1. *Pilot.* Run 10 tasks × 2 arms (no PRISM, hook) × 2 repetitions. Compute the spread of the paired log ratios and use it to set the final sample size (use the rough rule in 4.3 as a start: about 80 pairs for ±15 points).
2. *Task set.* At least 30 tasks across the types localise, edit, rename, bug fix, explain, and across at least 2 repositories (this repository and one outside repository). Hidden tests for scoring wherever possible.
3. *Arms.* no PRISM, grep-only, hook, hook + MCP, MCP lean (plus CLI-only once as a control).
4. *Design.* Paired and interleaved: each task × repetition runs all arms in the same window, in random order, in fresh isolated copies. Pin model, effort, host and PRISM versions.
5. *Metrics.* The T01 cost-weighted columns, tokens by class, turns, pass@1 and pass^k, tokens per solved task. Analysis on per-task log ratios with a paired bootstrap; show the baseline-usage covariate adjustment beside the raw numbers.
6. *Rules.* Decision thresholds and stopping point written down before the run. Cap spend per campaign and tell the owner the estimated cost first.
**Accept.** Protocol document and one full campaign with raw data committed. The README only claims what survives the paired comparison; anything else is reported as "not shown".

#### T42 — Embedding bake-off (P2, M)
**Goal.** Decide whether to replace the MiniLM-L6 semantic channel.
**Where.** `prism/semantic/` (or wherever the embedder lives; locate with `prism find "embedding model"`), `tests/benchmarks/`.
**Candidates.** CodeRankEmbed (137M, MIT, 8,192 tokens, needs `trust_remote_code`), jina-code-embeddings-0.5b (494M, 32k tokens, GGUF available; **check the licence before use**, it was not verified). Compare on T40 plus a code-to-code set drawn from this repository: recall@5/10, index time, index size, cold and warm query latency, memory, Windows install friction.
**Rules.** Keep the semantic channel optional and local; no `trust_remote_code` by default (pin a revision and ask the user, or vendor the modelling code under review). Keep the default install small.
**Accept.** A table and a recommendation; no default change without the owner's decision.

#### T43 — Post-edit hints experiment (P2, M)
**Goal.** Test the lexical-anchored expansion idea from LARGER (k=10, θ=0.5): after the agent edits a file, a small PostToolUse hint lists dependents likely to need the same change.
**Where.** `prism/hooks/` (post-edit hook exists), `prism/navigator/` graph queries.
**Steps.** Behind a config flag, off by default. Hint is at most about 150 tokens and only appears when dependents exist that the agent has not touched. Evaluate on the T41 protocol with edit tasks.
**Accept.** Keep only if it reduces failed or repeated edits without raising cost; otherwise delete the code.

#### T44 — LSP docs and doctor (P2, S)
**Goal.** Claude Code's LSP tool gives exact references and reportedly cuts tool-output tokens by 31–33%. Do not rebuild it; make sure PRISM and LSP complement each other.
**Where.** `docs/`, `prism/cli.py` (`doctor`).
**Steps.** Document when to use which (PRISM for ranked orientation and cross-file packets; LSP for exact definition, reference and rename). `doctor` notes whether a language server plugin is configured for the repository's main language.
**Accept.** Doc page and doctor line; no code dependency on LSP.

#### T45 — Dart, Kotlin and Swift parsing (P2, L)
**Goal.** Close the language gaps noted in the audit.
**Where.** `prism/parsing/` (check the actual directory), grammar vendoring, `tests/fixtures/`.
**Steps.** One language per PR. Tree-sitter grammar, symbol and call extraction, fixtures, incremental-equivalence test. Keep grammar packages optional extras so the base install stays small.
**Accept.** Each language indexes a fixture project with correct symbols and callers; `scan` ≡ `scan` + `update`.

#### T46 — Windows CLI latency (P2, S)
**Goal.** An earlier report put warm CLI calls near 1.3 s on Windows; the target is a p95 under 200 ms.
**Where.** `prism/cli.py` (lazy imports), `prism/navigator/daemon.py`, `prism/taskfast.py`, `pyproject.toml` entry points.
**Steps.** Measure with `python -X importtime`; move heavy imports (numpy, tree-sitter, semantic model) behind the commands that need them; route hook calls to the daemon where one exists; record cold and warm numbers.
**Accept.** `prism find`, `prism task` and the hooks meet the target on the owner's machine; numbers in `docs/benchmarks/`.

#### T47 — Cache cleanup (P2, S)
**Where.** `prism/outputfilter.py` (tee directory), `.aicontext/cache/`, `prism/cli.py` (`doctor`, a `prism cache gc` subcommand).
**Steps.** Cap the tee directory by count and size and age; `gc` reports what it removed; never touch the index or the notes.
**Accept.** Test with 500 synthetic tee files; limits respected; doctor reports cache size.

#### T48 — Archive dated documents (P2, S)
**Where.** `docs/`, `.gitignore`, `.aiignore` if present.
**Steps.** Move dated plan and audit files that are no longer active (including superseded versions of these two plans) into `docs/archive/` and exclude that directory from the index so stale prose is never retrieved as context.
**Accept.** `prism find` on a phrase from an archived document returns nothing from `docs/archive/`; links in live docs still resolve.

---

## 7. Earlier recommendations: verify first, then build

The 10 October deep dive recommended a number of things. The project's documents say most of them now exist. Do not rebuild them; confirm each in one command and close the item.

| Item | Docs say | Verify with | If missing |
|---|---|---|---|
| Twins line and batch line in packets | shipped | `prism task "<edit request>"` and look for `Twins:` / `Batch:` | open a task, small |
| `prism diff` (apply or preview a patch) | shipped | `prism diff --help` | covered by T05/T10 |
| `prism find` | shipped | `prism find "token estimate"` | — |
| `--detail brief/full` | shipped | `prism task --help` | — |
| Read-range hints (`read_next`) | shipped | packet footer | T12 refines |
| Verify mode and the gate (`GATE_BUDGET = 900`) | shipped | `prism hook --help`, `tests/integration/test_gate_dedupe.py` | — |
| Antigravity pre-invocation hook | shipped | `prism hook pre-invocation --help` | — |
| Dedupe-read hook (opt-in) | shipped | `prism/hooks/dedupe.py` | T25 hardens compaction |
| Work log and `prism recall` | shipped | `prism recall --help` | — |
| Semantic channel and local ranking feedback | shipped | `prism doctor` | T42 may replace the model |
| Delivery of old tool results as clearable (context editing) | not confirmed | read `prism/hooks/formats.py` | **open question** for the owner: only worth doing if Claude Code exposes it to hooks; verify against current docs before any work |
| "Done condition" line for edit tasks (what to run, which test) | not confirmed | grep packets for `Run:` or `Done:` | small task: reuse the `Tests:` line plus T26 |
| Test-time weighting of which tests to name | not confirmed | read `_related_tests` | T13 covers part of this |
| CLI latency | one report said ~1.3 s warm on Windows | time it | T46 |

Record the result of each check in the commit message of the first task that touches the area, or in `docs/benchmarks/` if no task does.

---

## 8. Roadmap and gates

Order matters: measure first, change second, re-run the replay after every phase. A phase is not done until its gate passes. If a gate fails, fix or revert; do not move on.

| Phase | When | Tasks | Gate |
|---|---|---|---|
| 0 — baseline and quick wins | days 1–2 | T00, T01, T02, T03, T04, T05 | baseline numbers committed; root `CLAUDE.md` ≤ 200 lines and ≤ 4k est. tokens in `/context`; every refused patch has a reason code; no hook output over the cap |
| 1 — packet precision | week 1 | T10, T11, T12, T13, T14, T15, T16a | replay: token precision ≥ 55%, file recall within 2 points of baseline, mean packet ≤ 1,000 est. tokens; large rename returns a patch; parity and determinism tests green |
| 2 — shell, context, memory, safety | weeks 2–3 | T20 (or its Branch B), T21–T30 | shell output ≥ 70% smaller with 100% of failure lines kept, or ADR 0007 written; injection fixtures pass; skills listing ≤ 1k est. tokens; one live pilot on one host; hook-only default decided (T22) |
| 3 — evidence and coverage | weeks 4–6 | T40–T48, T16b | live results with ≥ 5 repetitions per cell, paired baselines, split by task type, cost-weighted; each experiment adopted only if it meets its acceptance line |

Targets in one place:

| Metric | Today | Target | Measured by |
|---|---|---|---|
| Token precision (replay, HEAD index) | 37% | ≥ 55% | T00 |
| File recall (replay) | 62% | no drop over 2 points | T00 |
| Mean packet size | 1,406 est. tokens | ≤ 1,000 | T00 |
| Test share of packet characters, non-test requests | up to 18% | ≤ 3% | `packet_audit.py` |
| Large rename (80 hits) | no patch, 4.2k chars | checked patch, ≤ 400 est. tokens | T10 test |
| Line-number prefix share of packet characters | 9.7% | ≤ 3% | `packet_audit.py` |
| Estimator error on code | unknown (new tokenizer ≈ +30%) | ≤ 10% or a calibrated `token_scale` | T02 |
| Project memory in this repository | ≈ 17k est. tokens | ≤ 4k | `/context` |
| Shell output through the filter | not wrapped by default | ≥ 70% fewer tokens, 100% of failure lines kept | T20 corpus |
| Live saving | 53–57% total on one host and repository | reported per task type with intervals, cost-weighted; no fixed target claimed | T41 |

---

## 9. Prompts to give Claude Code

Paste the first block into a new Claude Code session opened in `D:\Projects\prism`. Use the later blocks to start each phase in a fresh session (the plan file carries the state, so no history is lost). Commit trailers for this repository follow whatever the session's commit-attribution setting says; do not hard-code any here.

### 9.1 Kickoff

```text
Read docs/master-improvement-plan-2026-10-11.md completely, then CLAUDE.md.

You are executing that plan on the PRISM repository. Rules:
1. Do section 0's four rules exactly. Do not run `prism init`, `prism scan`, `prism enable`, or `prism install --global` against this checkout; for experiments use a scratch copy.
2. First do task T00 (baseline). Do not change product code before the baseline numbers are committed.
3. Work through section 6 in order, one task per commit, Conventional Commits, one focused change each. Run `ruff`, `mypy` and the unit tests before every commit (see CLAUDE.md for the exact commands). Never skip hooks or tests.
4. Before building any task, check whether it is already done (section 7). If it is, write that down and move on.
5. Stop at each gate in section 8 and report the measured numbers against the targets. Do not continue past a failed gate.
6. If a task needs a network call, an LLM, or edits to user source code, stop and tell me instead of working around it.
7. Task T20 starts with an experiment. Do the experiment, report the result, and wait for my answer before choosing Branch A or B.
8. Ask me about anything listed under "Decisions for the owner" (section 11) when you reach a task that depends on it.

Start now with T00. Report briefly when Phase 0 is done.
```

### 9.2 Phase 0

```text
Read docs/master-improvement-plan-2026-10-11.md sections 0, 1, 6 (Phase 0) and 8. Execute T00 to T05 in order. Show me the baseline table (T00) and the new CLAUDE.md line counts (T03) when finished. Stop at the Phase 0 gate.
```

### 9.3 Phase 1

```text
Read docs/master-improvement-plan-2026-10-11.md sections 0, 1, 6 (Phase 1) and 8, and docs/benchmarks/replay-baseline-2026-10-11.md. Execute T10 to T16a in order. After each task re-run tests/benchmarks/replay_precision.py and packet_audit.py and put before/after numbers in the commit message. If recall drops by more than 2 points, revert that task and tell me. Stop at the Phase 1 gate.
```

### 9.4 Phase 2

```text
Read docs/master-improvement-plan-2026-10-11.md sections 0, 1, 6 (Phase 2) and 8. Start with the T20 experiment only and report what you find. After my answer, execute T21 to T30. Treat T27 as a security task: add the fixtures first. Stop at the Phase 2 gate.
```

### 9.5 Phase 3

```text
Read docs/master-improvement-plan-2026-10-11.md sections 0, 1, 6 (Phase 3) and 8. Execute T40 and T41 first and tell me the estimated cost of the live run before starting it. Then run T42 to T48 as separate experiments; for each one write down adopt, change or drop with the numbers. Do not change any default without my decision.
```

---

## 10. Sources

Official documentation (fetched 11 October 2026):
- Anthropic, [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — multipliers, TTL, invalidation, ordering, minimum lengths.
- Anthropic, [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — prices, cache-hit multipliers per model, tokenizer note.
- Claude Code, [Memory](https://code.claude.com/docs/en/memory) — 200-line target, imports, nested files, path-scoped rules, compaction behaviour.
- Claude Code, [Hooks](https://code.claude.com/docs/en/hooks) — 10,000-character cap, `additionalContext`, PreToolUse `updatedInput` and `permissionDecision`. Not fully read: the final 10,412 characters were not seen, which is why T20 starts with an experiment.
- Claude Code, [Skills](https://code.claude.com/docs/en/skills) — description budget, `disable-model-invocation`, 500-line guidance.
- Anthropic, [Context management](https://claude.com/blog/context-management) — context editing and memory tool.

Papers and studies:
- [ContextBench](https://arxiv.org/html/2602.05892v1) — retrieval benchmark for coding agents.
- [LARGER](https://arxiv.org/pdf/2605.16352) — lexically anchored repository graph retrieval.
- [Do Context Files Help Coding Agents?](https://arxiv.org/pdf/2607.27250) — two-agent ablation, 288 runs, 3 Python repositories.
- [LongCodeZip](https://arxiv.org/html/2510.00446v1) — model-based code compression.

Tools and independent write-ups (treat numbers as claims):
- [RTK](https://github.com/rtk-ai/rtk) — shell-output filtering proxy, self-reported savings.
- [Agent Patterns: PostToolUse output replacement](https://www.agentpatterns.ai/tool-engineering/posttooluse-output-replacement/) and the [issue report on `updatedToolOutput` being ignored for built-in tools](https://claudeissues.com/issue/67442-posttooluse-updatedtooloutput-silently-ignored-for-built-in-tools-bash-webfetch).
- [MCP context bloat fixes](https://mcp.directory/blog/mcp-context-bloat-fix-2026-tool-search-code-mode-progressive-disclosure) and [Reduce MCP token usage](https://aident.ai/blog/reduce-mcp-token-usage-claude-code-codex) — tool search, thresholds, `ENABLE_TOOL_SEARCH`.
- [Simon Willison on Claude token counts](https://simonwillison.net/2026/Apr/20/claude-token-counts/) — tokenizer uplift measurements.
- [CircleCI on Claude Code LSP](https://circleci.com/blog/claude-code-lsp/) — one repository, three tasks, two models.
- [CodeGraph write-up](https://pasqualepillitteri.it/en/news/11125/codegraph-cut-coding-agent-tokens) — 62% average token reduction claimed on seven repositories; the agent held about 80% more retrieval context at the end.
- [jCodeMunch listing](https://glama.ai/mcp/servers/jgravelle/jcodemunch-mcp) and [Claude Context evaluation](https://glama.ai/mcp/servers/@zilliztech/claude-context/blob/2484ae29b3a9c92815f1524cbb9924b3e241ec17/evaluation/README.md) — vendor-run benchmarks.
- [Aider token limits](https://fast.io/resources/aider-token-limit/) — repo-map budget defaults and refresh modes.
- [Repomix code compression](https://repomix.com/guide/code-compress) — signature extraction, no reduction figure published.
- [jina-code-embeddings](https://cms.jina.ai/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/) and [CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed) — embedding candidates.
- [Codex prompt-injection hardening](https://codex.danielvaughan.com/2026/04/21/prompt-injection-defence-codex-cli-attack-vectors-hardening/) — attack vectors and mitigations.

Also surveyed for section 2 (Headroom, context-mode, claude-mem, Mem0, Cline Memory Bank, Graphify, GitNexus, Serena, Codebase-Memory, the Obsidian/LLM-wiki method, caveman-style output skills, Windsurf Codemaps and SWE-grep): the figures in the table come from each project's own pages or single write-ups and were not independently checked. Search by tool name to re-read them.

Limits of this research: some pages were read through a summarising fetch tool, so exact wording may differ; several sources are single-repository or vendor-run; licences of several tools (Elastic License v2 for context-mode, PolyForm Noncommercial for GitNexus, GPL-3.0 for Serena) rule out copying their code into PRISM, so only ideas are adopted.

---

## 11. Risks and decisions for the owner

Risks
- **Recall loss from tighter selection (T11, T12).** Replay gate; the wide profile stays for medium or low confidence.
- **Agent behaviour changes when the layout changes (T14).** One live pilot before the new layout is default.
- **Host behaviour moves between Claude Code versions (T04, T20).** Hook features have been reported as ignored; add canary checks to `prism doctor` and fall back to documented behaviour.
- **Replay is a proxy.** Commit subjects are poor queries. Do not quote replay numbers as agent savings.
- **Single-repository, vendor-run evidence** for several external claims. They set direction only.
- **A hook that rewrites commands can widen permissions** if it is ever combined with "allow". PRISM never approves.
- **Schema changes (T16b)** need a migration and the full equivalence suite.

Decisions for the owner
1. Is a 2-point file-recall tolerance acceptable in exchange for the precision gain (T11, T12)?
2. Hook-only default and MCP opt-in (section 4.2) is the recommendation. Confirm it, or ask for the T22 comparison first (already the plan).
3. If the T20 experiment shows `updatedInput` needs "allow", confirm Branch B (documentation and doctor line only).
4. Should `token_scale` default to a calibrated value or stay at 1.0 (T02)?
5. Which host gets the live pilot first: Claude Code, Codex or Antigravity (T41)?
6. Is a model that needs `trust_remote_code` acceptable if vendored and pinned (T42), or ruled out?
7. Make `.claude/rules/` committable (negate it in `.gitignore`), or keep nested `CLAUDE.md` only (T03)?

---

## Appendix A — the audit request set

`tests/benchmarks/packet_audit_requests.json` (created in T00) holds ten requests, one per kind, so changes can be compared like for like. The kinds, as used in the 10 October audit:

| Kind | What it exercises | Known example |
|---|---|---|
| `broad` | vague change touching several modules | choose one about graph communities |
| `bug` | a defect in installer logic | a fault in `ClaudeCodeIntegration.plan` |
| `docs` | documentation-flavoured edit | a change to the `diff` command help |
| `edit-default` | change a default | change the default `budget` of `prism_task` |
| `edit-fn` | change one named function | "make the hook skip prompts shorter than 6 words" (M4) |
| `explain-arch` | overview, no edit | how the pieces fit together |
| `feature` | add a field to a writer | extend `add_decision` |
| `find` | locate where something lives | where seen ranges are saved |
| `rename` | mechanical rename | `render_task` to `render_packet` (M5) |
| `tests` | test-flavoured request | add a test for `_store` |

Write the exact request texts when you create the file, keep them fixed afterwards, and record in the file header that the first run was against commit `<sha>`. The audit's original request wording was not saved, so numbers will be close to M1–M7 but not identical.

---

## Appendix B — replay script (starting point for T00)

Needs `prism` on PATH and an indexed checkout. Saved here so T00 can start from it. Known limits: it indexes HEAD, not each commit's parent, and uses the subject line as the query.

```python
import os, re, subprocess

FENCE = "`" * 3  # the fence PRISM prints around source blocks

log = subprocess.run(
    ["git", "log", "--no-merges", "--format=@@%h|%s", "--name-only", "-n", "150"],
    capture_output=True, text=True,
).stdout
commits, cur = [], None
for line in log.split("\n"):
    if line.startswith("@@"):
        sha, subject = line[2:].split("|", 1)
        cur = {"sha": sha, "subject": subject, "files": []}
        commits.append(cur)
    elif line.strip() and cur:
        cur["files"].append(line.strip())

rows = []
for c in commits:
    gold = [f for f in c["files"] if f.startswith("prism/") and f.endswith(".py") and os.path.exists(f)]
    if not 1 <= len(gold) <= 4 or re.match(r"(docs|chore|ci|test)", c["subject"]):
        continue
    query = re.sub(r"^\w+(\([^)]*\))?!?:\s*", "", c["subject"])
    if len(query.split()) < 4:
        continue
    out = subprocess.run(
        ["prism", "task", query, "--budget", "2000", "--session", "replay-" + c["sha"]],
        capture_output=True, text=True,
    ).stdout
    blocks = re.findall(
        r"^candidate: (\S+?):(\d+)-(\d+)[^\n]*\n" + FENCE + r"\n(.*?)\n" + FENCE, out, re.S | re.M
    )
    code = sum(len(b[3]) for b in blocks)
    useful = sum(len(b[3]) for b in blocks if b[0] in gold)
    hit = len({b[0] for b in blocks} & set(gold))
    rows.append((len(gold), hit, code // 4, useful // 4, len(out) // 4))

if not rows:
    raise SystemExit("no usable commits in the last 150")
n = len(rows)
print("queries:", n)
print("file recall: %.0f%%" % (100 * sum(r[1] for r in rows) / sum(r[0] for r in rows)))
print("any-hit rate: %.0f%%" % (100 * sum(r[1] > 0 for r in rows) / n))
print("token precision: %.0f%%" % (100 * sum(r[3] for r in rows) / max(1, sum(r[2] for r in rows))))
print("mean packet est. tokens: %d" % (sum(r[4] for r in rows) / n))
```

---

## Appendix C — what not to do

| Idea | Why not |
|---|---|
| Model-based context compression (LongCodeZip-style scoring, summarising reflectors) | needs a model call; breaks the no-LLM rule. Its deterministic parts (function/class chunking, knapsack selection) are adopted in T11 |
| Cloud vector search (Claude Context style) | needs a vector database and an embedding API; its published evaluation is 30 instances and one small model |
| Copying symbol-server products with 90+ tools (jCodeMunch) or code from licence-restricted tools (context-mode, GitNexus, Serena) | vendor-run numbers, restrictive licences, large tool surface; adopt ideas only |
| Compact notations such as TOON | savings only on large uniform tables and model-dependent |
| A signatures-only repository dump (Repomix compress) | no published reduction figure; the overview packet already does this selectively |
| Rewriting tool output by default, or relying on `updatedToolOutput` | irreversible, can hide failures, reported ignored for built-in tools. Filter opt-in, keep the full text (T21) |
| Any hook that approves a command | widens permissions; PRISM hooks only add context or deny |
| Always-loaded memory files (Memory Bank style) | stale risk and a cost on every turn; use on-demand retrieval |
| Terse-output skills as a token strategy | output is a small share of cost and measured savings are 12–23% |
| Chasing a 70% average everywhere | small single-site edits cannot reach it; report by task type (T41) |
