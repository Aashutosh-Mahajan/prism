# PRISM — token-efficiency improvement and addition plan (11 October 2026)

Status: proposal. Nothing in this file has been implemented.
Inputs: a code and output audit of PRISM on 10 October 2026 (measured on a scratch copy, section 3), the earlier research notes in this folder, and a new web pass on 11 October 2026 (section 9).
Earlier notes this plan builds on and does not repeat: [`research-token-efficiency-2026-10-10.md`](research-token-efficiency-2026-10-10.md), [`research-deep-dive-2026-10-10.md`](research-deep-dive-2026-10-10.md), [`improvement-plan-2026-10-10.md`](improvement-plan-2026-10-10.md), [`trust-and-token-fixes-2026-10-10.md`](trust-and-token-fixes-2026-10-10.md), [`final-report-2026-10-10-v2.md`](final-report-2026-10-10-v2.md).

Conventions: "est. tokens" means PRISM's own chars/4. Vendor and self-reported figures are labelled as such. "Estimate" means my arithmetic or judgement, not a measurement. Priorities: P0 do first, P1 next, P2 later. Effort: S under a day, M a few days, L a week or more.

---

## 1. Summary

1. **The packet is the main in-product lever, and it is bigger than it needs to be.** Measured on 10 requests, 67% of packet characters are source code, but in a replay of 38 past commits only 37% of delivered code tokens were in files that were actually edited (section 3). Tighter block selection, excerpts centred on the match, and fewer test blocks are the highest-value changes (A1–A3).
2. **Mechanical changes fall off a cliff at 40 sites.** Renaming a function with 7 sites gets a checked patch and a 3.6k-character packet. Renaming one with 80 word hits gets no patch, no exhaustive list and a 4.2k-character source dump (B1). This is the cheapest large win, because a patch replaces dozens of agent edit calls.
3. **At current prices, cache reads are nearly free; new context, output and turns are what cost money.** Sonnet 5.5 and Opus 5.5 read cached input at 0.05× the input price, output costs 5× input, and the newer tokenizer produces about 30% more tokens than Sonnet 4.6 and earlier (section 2). Our metric should be cost-weighted and should count turns and output, not just "total tokens" (D1).
4. **Your own `CLAUDE.md` is the largest single standing cost in this repository.** It is 68 KB, about 17k est. tokens, against Claude Code's documented target of under 200 lines. Imports do not help; path-scoped rules do (F1).
5. **Delivery has three traps to design around:** the hook context cap of 10,000 characters, MCP tools being deferred by default in Claude Code (so an MCP-only install costs an extra search turn), and `updatedToolOutput` being reported as ignored for built-in tools (C2–C4).
6. **Independent evidence says context files do not raise pass rates; they change cost and process.** The useful content is cost warnings (for example "the full suite takes 20 minutes"), and, for Claude Code, selective retrieval used fewer cache-creation tokens than always-on injection (C9).
7. **New content to add:** auto-wrapping noisy shell commands in `prism filter` (C1), edge-confidence labels (A7), a cost-weighted benchmark and an offline replay gate in CI (D1, D2), an injection-hardening pass now that Markdown/JSON/YAML text enters packets (G1), and an embedding bake-off for the optional semantic channel (E2).
8. **What this plan will not do:** it does not add LLM-based compression, cloud embeddings or exotic output notations (section 8).

Estimated combined effect (estimate, not measured): typical packet 1.4k → 0.7–0.9k est. tokens (A1–A5); mechanical changes −70% or more of agent calls where a patch applies (B1); dev sessions in this repository −13k tokens per model call (F1). Every item has an acceptance test so these can be checked rather than believed.

---

## 2. Ground truth: what a token costs now

From the Anthropic pricing and prompt-caching pages (see section 9).

| | Sonnet 5.5 | Opus 5.5 | Fable 5.1 | Haiku 5.5 (≤100k prompt) |
|---|---|---|---|---|
| Input per M tokens | $2 | $4 | $10 | $0.10 |
| Output per M tokens | $10 | $20 | $50 | $0.50 |
| Cache write, 5 min / 1 h | 1.25× / 2× | 1.25× / 2× | 1.25× / 2× | 1.25× / 2× |
| Cache read | **0.05×** | **0.05×** | **0.025×** | 0.1× |

- Output is 5× input on every current model. The cache lifetime is 5 minutes by default, refreshed on each read; a longer idle gap pays the write again.
- A change to tool definitions invalidates tools, system and messages; a system-prompt change invalidates system and messages; message edits only invalidate messages. Content before the breakpoint must be byte-identical.
- Models from 4.7 onward use a tokenizer that gives roughly 30% more tokens for the same text. **PRISM's chars/4 estimate was set before that and has never been calibrated** (A6).
- `improvement-plan-2026-10-10.md` item 19 assumes cache read at 0.1×. That is wrong for Sonnet 5.5 and Opus 5.5 and should be per model (D1).

Worked example (arithmetic from the published prices, Sonnet 5.5, not measured). A 1,400 est.-token packet injected on call 1 of a 20-call session costs about $0.0035 to write and 19 × $0.00014 ≈ $0.0027 to re-read, so about **$0.006**. One avoided model turn at 25k context saves about $0.0025 of cache reads plus a few hundred output tokens (about $0.003), plus the tool-result tokens that turn would have written. So:

- Shrinking the packet is worth doing, but mostly for **latency and context quality**, not for cache-read cost.
- **Avoiding turns, avoiding output, and avoiding new tool-result tokens** are where money is saved. That agrees with the earlier finding that call count is the driver.
- Cold-cache cost scales with fixed context: a 17k-token `CLAUDE.md` is about 17,000 × $2.5/M ≈ $0.04 every time the 5-minute cache lapses (before any tokenizer uplift).

---

## 3. Audit measurements this plan rests on

Run on 10 October 2026 on a scratch copy of the source (229 files indexed), not on the live repository, and without any agent. Replay and composition numbers use PRISM's own chars/4.

| ID | Finding | Evidence |
|---|---|---|
| M1 | Packets are large and fill the budget | 10 requests: 4.4k–7.1k characters (1.1k–1.8k est. tokens); at least two printed 2000/2000 |
| M2 | Composition of 10 packets (61.7k chars) | source code 67.4%; callers 6.3%; candidate headers 4.6%; test code 2.0% (18% in the rename packet); next/batch 2.4%; calls 1.4%; missing-source 1.3% |
| M3 | Retrieval precision against git history | 38 focused code commits, subject as query, HEAD index: file recall 62%, any-hit 82%, **token precision 37%**, mean packet 1,406 est. tokens. A rough proxy: subjects are terse and HEAD post-dates the commits |
| M4 | Excerpt shape | "make the user-prompt hook skip prompts shorter than 6 words": a 79-line `user_prompt` body (about 900 est. tokens) was sent; `MIN_WORDS` (`prompt.py:21`) was listed under "Missing source" |
| M5 | Mechanical-change cliff | rename with 7 sites → `Patch:` line, 3.6k chars. `estimate_tokens` (80 word hits) → no patch, 4.2k chars. `render_task` (31 hits) → no patch, 6.7k chars, cause not determined. `MAX_NAMED_LINES = 40` explains the first, not the second |
| M6 | Callers section | 45% of caller characters are test files (they repeat the `Tests:` line); 31% are dotted qualified names that repeat the path |
| M7 | Formatting overhead in code blocks | per-line number prefixes 9.7% of code characters; docstring/comment-start lines 10.4%; blank lines 0.6% |
| M8 | Fixed overhead of an installed Claude Code setup | MCP schema 1,001 chars (one tool, about 250 est. tokens); MCP instructions 234; SessionStart 430; `CLAUDE.md` block 739; skill 4,260 bytes (description always loaded, body on use). Small |
| M9 | This repository's own context file | `CLAUDE.md` 68,361 bytes; sections 12, 11, 8, 9 are 8.3, 7.7, 7.6 and 5.8 KB; section 19 (roadmap) still lists phases 0–5 as future work |
| M10 | Caches | `source-v2.sqlite` (3.3 MB) left beside `source-v3.sqlite`; `.aicontext/cache` is 19 MB |

---

## 4. Workstream A — packet precision and size (P0/P1)

Goal: the same or better edit success from a smaller, more precise packet. Gate for the whole workstream is D2 (offline replay): file recall must not drop by more than 2 points while token precision rises.

### A1. Tighter block selection (P0, M)
- **What:** For `edit` intent with high confidence, use the existing tight profile (`TIGHT_RELATIVE_SCORE = 0.5`, `TIGHT_MAX_BLOCKS = 3`) instead of `MIN_RELATIVE_SCORE = 0.25` and `MAX_BLOCKS = 6`. Replace greedy fill with a deterministic 0/1 knapsack over blocks (score per block, token cost per block, budget as capacity). LongCodeZip uses the same knapsack idea with model-based scores; here the scores stay lexical and graph-based, so the no-LLM rule holds.
- **Why:** M1–M3. ContextBench finds retrieval is judged on precision as well as recall, and that agents lose much of what they retrieve before patching ("usage drop").
- **Where:** `prism/navigator/task_pack.py` (`_select`, `_fit_blocks`, constants at the top).
- **Accept:** on the replay set, token precision ≥ 55% (from 37%), file recall ≥ 60%, mean packet ≤ 1,000 est. tokens.
- **Risk:** lower recall on vague requests. Mitigation: keep the wide profile when confidence is medium or the request names nothing exactly.

### A2. Excerpts centred on the match (P0, M)
- **What:** Show the window around matched lines (query terms, literals, edit anchors) instead of the head of the function. Lower `WHOLE_SYMBOL_MAX` from 120 to about 40 for every block except the top one. Secondary blocks show signature plus match windows.
- **Why:** M4. SWE-agent's interface study found a ~100-line window beat both 30 lines and the whole file, so the aim is bounded windows around the point of interest, not smaller for its own sake.
- **Accept:** on the 10 audit requests, 100% of request-matched lines appear in the packet; no named symbol appears under "Missing source".

### A3. Tests are listed, not shown (P0, S)
- **What:** Drop test files from candidate source blocks unless the request mentions tests or a test file; drop test callers from "Callers" when the `Tests:` line already names the file; cap test entries at 2.
- **Why:** M2, M6.
- **Accept:** test-file share of packet characters ≤ 3% on non-test requests.

### A4. Format compaction (P1, S)
- **What:** (a) number only the first line of each source block plus literal-list lines and "missing source" ranges, since the header already gives the range; (b) drop the dotted qualified name where it repeats the path, and group callers by file (`entry.py:91, antigravity.py:109`); (c) strip docstring bodies in non-primary blocks.
- **Why:** M6, M7. About 10–15% of characters, no information loss for edits (the Edit tool matches strings, not line numbers).
- **Accept:** ≥ 12% fewer characters at equal located content; golden-file test for the new layout; check that agents can still form `Read(offset, limit)` from the header range.

### A5. Budget ladder and repo-size scaling (P1, M)
- **What:** Give CLI and MCP the same ladder the hook already has (start ~1,200 est., expand only if the packet is not sufficient). For `edit-ready` exhaustive results use `--detail brief` by default. Scale the default with repository size and graph density instead of a flat 2000.
- **Why:** Aider's repo map defaults to 1,024 tokens, and its own guidance is about 512 for small projects and 2–4k for large cross-module ones. PRISM's flat 2000 is above that for small repositories.
- **Accept:** mean est. tokens ≤ 1,000 on the audit set with the same "sufficient" rate.

### A6. Calibrate the estimator (P0, S)
- **What:** Run 50 packets (code, prose, digits, JSON) through Anthropic's token-counting endpoint for each current model family and store a per-content-type ratio. Keep chars/4 as the offline default but make the ratio configurable, and report both in benchmark output.
- **Why:** the newer tokenizer gives about 30% more tokens on the same text, so "2000 est." probably means more. I could not check offline: the tokenizer download was blocked from the audit environment.
- **Accept:** |estimate − real| / real ≤ 10% on code packets for the supported models.

### A7. Edge-confidence labels and caller pruning (P1, M)
- **What:** Mark each call edge as resolved or heuristic (by provenance: import-resolved, same-class, name-only). Show resolved callers first, cap heuristic ones, and label them.
- **Why:** LARGER keeps neighbours only above an edge-confidence threshold (0.5 in its defaults) and reports a 13.5% Acc@5 drop when graph expansion is removed, so graph evidence helps only when filtered. The static call graph misses dynamic calls; telling the agent which edges are guesses lets it grep only those.
- **Accept:** callers section −40% characters; true-caller recall unchanged against an LSP or grep oracle on two repositories.

---

## 5. Workstream B — mechanical changes (P0)

### B1. Remove the 40-site cliff for rename and replace (P0, M)
- **What:** For rename and value-change intents, raise `MAX_NAMED_LINES` (suggest 400) and `MAX_FILES_PER_LITERAL`, and print only the count, the files, the `Patch:` command and the tests (target ≤ 400 est. tokens). Do not print source for sites the patch already covers.
- **Why:** M5. A patch replaces dozens of read-then-edit pairs. The earlier research already named "diff for mechanical changes" the largest single win.
- **Accept:** renaming `estimate_tokens` (80 word hits) returns a `Patch:` line that passes `git apply --check`, in a packet ≤ 400 est. tokens.

### B2. Say why there is no patch (P0, S)
- **What:** `prism diff` and the packet name the reason code ("sites not exhaustive", "new name already exists", "git rejected the diff", "too many sites"). Trace the `render_task` case, which has 31 hits and no patch for a reason I did not find.
- **Accept:** every refusal carries a reason; `render_task` either patches or states a real conflict.

### B3. Separate code from prose in patches (P2, M)
- **What:** Group hits into code, tests, docs/config. The patch covers code and tests by default; docs/config are an optional second patch.
- **Why:** since the 10 October change, Markdown/JSON/YAML text is searched, so a rename in this repository also hits historical reports.
- **Accept:** default patch touches no file under `docs/archive/` (see F2).

---

## 6. Workstream C — delivery and host integration

### C1. Auto-wrap noisy shell commands (P1, M)
- **What:** An opt-in PreToolUse hook on Bash that rewrites known noisy commands (test runners, builds, linters, package installs) to `prism filter -- <command>`. Today the filter works only if the agent chooses to prefix it. Keep ADR 0004's invariants: failure lines and their context are never dropped; the full output is saved and its path printed.
- **Why:** RTK does exactly this and reports (self-reported, bash output only, bytes/4) about 90% less output for common test runners and 75–85% for several linters and builds; it also saves the full output on failure. Its own caveat applies: savings are on shell output, not on the bill.
- **Where:** `prism/integrations/claude_code.py`, `prism/outputfilter.py`, a new `pre-tool-use` hook.
- **Accept:** on 10 recorded test/build runs, ≥ 70% fewer output tokens and 100% of failure lines retained. A kill switch (`PRISM_FILTER=0`) and a `doctor` check that the rewrite is honoured by the installed Claude Code version.
- **Risk:** reports of `updatedInput` being ignored for some tools (see C2); verify on the target version before enabling by default.

### C2. Do not depend on `updatedToolOutput` (P0, S)
- **What:** Documentation describes `updatedToolOutput` as replacing a tool's result, but several issue reports say it is silently ignored for built-in tools (Bash, WebFetch) in versions from 2.1.121 to 2.1.177, and the one I read was closed as a duplicate with no fix confirmed. Use `additionalContext` (reported working) and PreToolUse rewriting instead. Add a `prism doctor` canary that tests whether replacement is honoured and says so.
- **Accept:** `doctor` prints "output replacement: honoured / ignored / untested" per host.

### C3. Guard the hook size cap (P0, S)
- **What:** Claude Code caps each hook string (`additionalContext`, `systemMessage`, plain stdout) at 10,000 characters; above that it saves the text to a file and shows the model only the path and the first 2,000 characters. `prompt_budget` is allowed up to 8,000 est. tokens (about 32,000 characters), so a generous setting would silently become a 2,000-character preview. Clamp the Claude Code hook output to under 10,000 characters and warn in `doctor` when the configured budget exceeds it.
- **Accept:** unit test for the clamp; `doctor` warning.

### C4. Hook or MCP, not both by default (P1, S)
- **What:** When the prompt hook is installed on Claude Code, do not register the MCP server by default; offer `--mcp` explicitly. Claude Code defers MCP tool definitions by default (and automatically above 10% of context), which saves schema tokens but means the agent must search for `prism_task` first, an extra turn. The hook avoids that turn. The 7 October pilot also showed the MCP arm using more input than the CLI arm.
- **Open question:** I found no documented way for a server to mark its tool as always loaded. Check the current Claude Code docs before deciding what an MCP-only install should do.
- **Accept:** `/context` before and after shows the fixed-overhead change; benchmark arm "hook only" vs "hook + MCP".

### C5. Skills: zero standing cost for the optional ones (P1, S)
- **What:** Skill descriptions are listed in context every turn (each description plus `when_to_use` is truncated at 1,536 characters). Set `disable-model-invocation: true` on `prism-audit`, `prism-refresh` and `prism-decisions` so they cost nothing until invoked. Cut the `prism-context` body (4.3 KB; step 2 is a single ~330-word paragraph) to about 1.5 KB and move detail to a `reference.md` loaded on demand. Keep the description short and front-load the use case.
- **Accept:** the skill listing shows ≤ one short entry for PRISM by default; the body fits in 40 lines.

### C6. One source for all instruction text (P1, M)
- **What:** Generate the `CLAUDE.md` block, `AGENTS.md` block, skill, MCP instructions and SessionStart text from a single template with per-transport variants. The same rules currently live in five places and have needed aligning before (see `phase-status.md`, P0 delivery reliability).
- **Accept:** golden-file test; changing a rule changes every surface or fails CI.

### C7. Compaction safety (P1, S)
- **What:** Confirm that the task packets' "already sent" ranges reset when the host compacts. After compaction the agent no longer holds code PRISM thinks it sent, so references to "earlier code" force re-reads. The read-dedupe hook already resets on compaction; the packet session store may not. Project-root `CLAUDE.md` is re-read after compaction per the Claude Code docs, so the managed block survives.
- **Accept:** integration test: after a simulated compaction event the next packet resends source.

### C8. Packet awareness of cache-friendly delivery (P2, S)
- **What:** Keep injected text append-only and the header byte-stable; never rewrite earlier turns. Document that a hook-injected packet is persistent context and cannot be cleared, while a tool-result packet can be cleared by hosts that do context editing.
- **Why:** prompt caching needs byte-identical prefixes; context editing is reported (Anthropic, internal evaluation) to cut tokens 84% on a 100-turn test, but details were not published on the page I read.

### C9. Cost warnings, the one thing context files were shown to help (P1, S)
- **What:** Record wall-clock durations when tests run through `prism filter` and add one short line to packets: "full suite ≈ 14 min; run these targeted tests". Only when measured > 60 s, at most about 30 tokens.
- **Why:** in a controlled two-agent study the only context content that helped was a warning that the full test suite takes over 20 minutes; pass rates did not change, but agents ran fewer full-suite runs. Selective retrieval also used fewer cache-creation tokens than always-on injection (11 of 11 tasks lower).
- **Accept:** line appears only with a recorded duration; ≤ 30 est. tokens.

---

## 7. Workstreams D–G

### D. Measurement (P0 for D1 and D2)

**D1. Cost-weighted, per-model metric (P0, S).** Report per task: new-context tokens (cache writes plus uncached input), cache reads, output tokens, model turns, and dollars using the table in section 2, plus tokens per solved task and pass^k. Update `improvement-plan-2026-10-10.md` item 19. A "total tokens" headline overweights cache reads that cost 5% of input.

**D2. Offline replay gate in CI (P0, M).** Turn the audit's git-history replay into `tests/benchmarks/replay_precision.py`. For each focused code commit, use the subject as the query and the changed files and hunks as gold; report file recall, token precision, block and line recall, and mean packet size. It needs no LLM and no network. Gate: no recall regression over 2 points; precision must not fall. A starting script is in the appendix. Caveat to fix in the real version: build the index at the parent commit, not HEAD.

**D3. ContextBench scoring, offline (P1, L).** ContextBench provides 1,136 issue tasks over 66 repositories and 8 languages with human-annotated gold context, scored at file, block and line level, with a 500-task Lite subset. Score PRISM's packets against that gold without running an agent. It reports block-level F1 below 0.45 and line-level F1 below 0.35 for the agents it tested, which gives a reference line.

**D4. Better live benchmarks (P1, L).** At least 5 repetitions per cell, paired same-day baselines, bootstrap intervals, three repositories including one Java or Go and one TypeScript, results split by task type (single-site edit, mechanical change, multi-file change, explain). Single-site edits cannot reach a 70% saving and should not be averaged with the rest. Ceiling analysis is in `research-token-efficiency-2026-10-10.md`, section 5.

### E. Retrieval additions

**E1. Lexical-anchored graph hints on the agent's own searches (P2, M, experimental).** LARGER appends confidence-filtered graph neighbours to the agent's grep output (k = 10, confidence ≥ 0.5, at most 20 neighbours per file) and reports 87.0 vs 74.1–75.2 file-level Acc@5 on LocBench against Codex and Claude Code, with about 24–32% fewer tokens than Codex in its own runs (353K vs 522K on MuLocBench, 452K vs 591K on LocBench). A PostToolUse `additionalContext` on Grep/Glob could do the same from PRISM's graph (append mode is documented; only replace mode is reported broken). Cap at 150 est. tokens and enable only if D4 shows a net saving.

**E2. Embedding bake-off for the optional semantic channel (P1, M).** The current default is a small general text model (MiniLM) run on NumPy. Candidates:

| Model | Size | Context | Reported quality | Notes |
|---|---|---|---|---|
| MiniLM-L6 (current) | ~22M | short | with MiniLM on, top-three source recall rose from 62.5% to 75% on eight paraphrases (`phase-status.md`) | already works offline on NumPy |
| CodeRankEmbed | 137M | 8,192 | CoIR NDCG@10 60.1; MIT licence | needs a fixed query prefix and `trust_remote_code=True` (custom code), which conflicts with a no-remote-code stance unless vendored |
| jina-code-embeddings-0.5b | 494M | 32,768 | 78.41% average over 25 code benchmarks, ahead of Qwen3-Embedding-0.6B (73.49%) | GGUF 1–4 bit available; licence not stated on the page I read, so check before any use |

Accept only if recall@3 on the paraphrase set improves by ≥ 10 points, it runs with no network and no remote code execution, and cold-start stays acceptable. A 6 GB GPU fits the 0.5B model; users without a GPU should not be forced to wait on it. Otherwise keep MiniLM.

**E3. Exact references from a language server (P2, S docs / L integration).** Claude Code has a built-in LSP tool through code-intelligence plugins. A published benchmark on a 149k-line TypeScript repository found LSP cut tool-output tokens about 31–33% against grep and found every reference where two grep runs missed some (9 of 11 and 249 of 260). PRISM's static graph cannot be exact for dynamic calls. Plan: document LSP as the complement, make `prism doctor` suggest it for typed languages, and rely on A7's labels rather than building language-server support into PRISM. The cost is memory and cold start on large workspaces.

**E4. Mobile languages (P2, L, carry-over).** Dart, Kotlin and Swift symbol parsing. ArogyaTrack, the main benchmark repository, includes Flutter code that is searched for literals but not parsed for symbols.

### F. This repository's own hygiene (P0 for F1)

**F1. Split `CLAUDE.md` (P0, S).** Claude Code's documentation says to target under 200 lines per file, that longer files cost context and reduce adherence, that `@path` imports **do not** reduce cost because imports load at launch, and that path-scoped rules (`.claude/rules/*.md` with a `paths:` field) load only when matching files are touched. It also warns at startup when a file is over the limit, and the project-root file is re-read after compaction. Plan: keep a core of about 150 lines (principles, commands, layout, conventions, "before you add anything"); move sections 8, 9, 11, 12 and 13 to `docs/spec/`, and use path-scoped rules for the parts that matter only in `viewer/**`, `prism/integrations/**` or `prism/navigator/**`; delete or rewrite the stale roadmap (section 19) and the sections `prism` can generate (14, 15).
- **Accept:** `/context` shows project memory ≤ 4k est. tokens; no startup length warning; a test keeps `CLAUDE.md` under 200 lines including the block PRISM appends.
- **Effect:** about 13k fewer tokens in every model call of a development session here (estimate; more under the newer tokenizer).

**F2. Archive dated reports (P1, S).** Move dated benchmark and research reports to `docs/archive/` and add it to `[tool.prism] ignore`, so historical text does not appear in "exhaustive" literal lists for this repository. Move root `update.md` (32 KB) into `docs/`.

**F3. Cache garbage collection (P2, S).** Remove superseded cache files (`source-v2.sqlite` beside `source-v3.sqlite`) on upgrade.

### G. Trust and safety (P1)

**G1. Treat packet text as untrusted data (P1, M).** Hook output enters the model as user-level context, and since 10 October it can include lines from Markdown, JSON, YAML and templates. Published hardening guidance lists repository files (including HTML comments in READMEs), `AGENTS.md`/`SKILL.md` edits and MCP results as injection vectors, and a December 2025 case used hidden Unicode in a branch name. The same article does not discuss hook output. Plan: label lines that come from non-code files; strip HTML comments and zero-width and bidirectional control characters from rendered snippets; keep the 220-character cap; keep the "data, not instructions" framing in the header; add fixture tests with embedded instructions. Claude Code already escapes a `<system-reminder>` tag inside hook strings. This reduces exposure; it cannot remove it.
- **Accept:** injection fixtures are rendered without the hidden characters or comments; snippets from non-code files are labelled.

---

## 8. What not to do

| Idea | Why not |
|---|---|
| Model-based context compression (LongCodeZip-style perplexity scoring, summarising reflectors) | needs a model call; breaks the no-LLM rule. Its deterministic parts (function/class chunking, knapsack selection) are adopted in A1 |
| Cloud vector search (Claude Context style) | needs a vector database and embedding API. Its published evaluation was 30 instances, one small model, 3 runs, a 39.4% token reduction at equal F1 of 0.40 |
| Copying symbol-server products with 90+ tools (jCodeMunch) | vendor-run numbers, restrictive licence, large tool surface; PRISM's one-tool design is the better direction |
| Compact notations such as TOON | savings only on large uniform tables and model-dependent (see the 10 October deep dive) |
| A signatures-only repository dump (Repomix compress) | no published reduction figure; PRISM's overview packet already does this selectively |
| Rewriting tool output by default | irreversible and can hide failures; do it opt-in with tee, as in C1 |
| Chasing a 70% average everywhere | small single-site edits cannot reach it; report by task type (D4) |

---

## 9. Sources

Official documentation (fetched 11 October 2026):
- Anthropic, [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — multipliers, TTL, invalidation, ordering, minimum lengths.
- Anthropic, [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — prices, cache-hit multipliers per model, tokenizer note.
- Claude Code, [Memory](https://code.claude.com/docs/en/memory) — 200-line target, imports, path-scoped rules, compaction behaviour.
- Claude Code, [Hooks](https://code.claude.com/docs/en/hooks) — 10,000-character cap, UserPromptSubmit, PostToolUse, `if` conditions. (I read the first 100,000 of 110,412 characters; the PostToolUse decision section was truncated.)
- Claude Code, [Skills](https://code.claude.com/docs/en/skills) — description budget, `disable-model-invocation`, 500-line guidance.
- Anthropic, [Context management](https://claude.com/blog/context-management) — context editing and memory tool, internal results.

Papers and studies:
- [ContextBench](https://arxiv.org/html/2602.05892v1) — retrieval benchmark for coding agents.
- [LARGER](https://arxiv.org/pdf/2605.16352) — lexically anchored repository graph retrieval.
- [Do Context Files Help Coding Agents?](https://arxiv.org/pdf/2607.27250) — two-agent ablation, 288 runs, 3 Python repositories.
- [LongCodeZip](https://arxiv.org/html/2510.00446v1) — model-based code compression.

Tools, independent write-ups and vendor claims (treat numbers as claims):
- [Agent Patterns: PostToolUse output replacement](https://www.agentpatterns.ai/tool-engineering/posttooluse-output-replacement/) and the [issue report on `updatedToolOutput` being ignored](https://claudeissues.com/issue/67442-posttooluse-updatedtooloutput-silently-ignored-for-built-in-tools-bash-webfetch).
- [RTK](https://github.com/rtk-ai/rtk) — shell-output filtering proxy, self-reported savings.
- [MCP context bloat fixes](https://mcp.directory/blog/mcp-context-bloat-fix-2026-tool-search-code-mode-progressive-disclosure) and [Reduce MCP token usage](https://aident.ai/blog/reduce-mcp-token-usage-claude-code-codex) — tool search, thresholds, `ENABLE_TOOL_SEARCH`.
- [Simon Willison on Claude token counts](https://simonwillison.net/2026/Apr/20/claude-token-counts/) — tokenizer uplift measurements.
- [CircleCI on Claude Code LSP](https://circleci.com/blog/claude-code-lsp/) — one repository, three tasks, two models.
- [CodeGraph write-up](https://pasqualepillitteri.it/en/news/11125/codegraph-cut-coding-agent-tokens) — 62% average token reduction claimed on seven repositories, one architecture question, four runs; the agent held about 80% more retrieval context at the end.
- [jCodeMunch listing](https://glama.ai/mcp/servers/jgravelle/jcodemunch-mcp) and [Claude Context evaluation](https://glama.ai/mcp/servers/@zilliztech/claude-context/blob/2484ae29b3a9c92815f1524cbb9924b3e241ec17/evaluation/README.md) — vendor-run benchmarks.
- [Aider token limits](https://fast.io/resources/aider-token-limit/) — repo-map budget defaults and refresh modes.
- [Repomix code compression](https://repomix.com/guide/code-compress) — tree-sitter signature extraction, no reduction figure published.
- [jina-code-embeddings](https://cms.jina.ai/jina-code-embeddings-sota-code-retrieval-at-0-5b-and-1-5b/) and [CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed) — embedding candidates.
- [Codex prompt-injection hardening](https://codex.danielvaughan.com/2026/04/21/prompt-injection-defence-codex-cli-attack-vectors-hardening/) — attack vectors and mitigations.

Limits of this research: some pages were read through a summarising fetch tool, so exact wording may differ; several sources are single-repository or vendor-run; I did not find an authoritative source for position effects of injected context, so no item here depends on one.

---

## 10. Roadmap and gates

Order matters: measure first (D1, D2), change second, and re-run the replay after every phase. A phase is not done until its gate passes.

| Phase | When | Items | Gate |
|---|---|---|---|
| 0 — baseline and quick wins | days 1–2 | D1, D2 (record baseline), A6, F1, C2, C3, B2 | baseline numbers committed; `CLAUDE.md` ≤ 200 lines; reason codes shown for every refused patch |
| 1 — packet precision | week 1 | A1, A2, A3, B1, C5 | replay: token precision ≥ 55%, file recall within 2 points of baseline, mean packet ≤ 1,000 est. tokens; large rename returns a patch |
| 2 — format and delivery | week 2 | A4, A5, A7, C1, C4, C6, C7, C9, F2, G1 | replay still passing; one live pilot on one host (hook only vs hook + MCP); injection fixtures pass; shell filter keeps 100% of failure lines |
| 3 — proof and retrieval | weeks 3–4 | D3, D4, E2, E1 (experiment) | live results with at least 5 repetitions per cell, paired baselines and intervals, split by task type; E2 adopted only if it meets its acceptance line |
| 4 — later | after phase 3 | E3, E4, B3, F3, C8 | per item |

Acceptance targets in one place:

| Metric | Today | Target | Measured by |
|---|---|---|---|
| Token precision (replay) | 37% | ≥ 55% | D2 |
| File recall (replay) | 62% | no drop over 2 points | D2 |
| Mean packet size | 1,406 est. tokens | ≤ 1,000 | D2 |
| Test share of packet characters, non-test requests | up to 18% | ≤ 3% | audit script |
| Large rename (80 hits) | no patch, 4.2k chars | patch, ≤ 400 est. tokens | B1 test |
| Estimator error on code | unknown (new tokenizer ≈ +30%) | ≤ 10% | A6 |
| Project memory in this repository | ≈ 17k est. tokens | ≤ 4k | `/context` |
| Shell output through the filter | not wrapped by default | ≥ 70% fewer tokens, 100% of failure lines kept | C1 |
| Live saving | 53–57% total on one host/repository | reported per task type with intervals, cost-weighted; no fixed target claimed | D4 |

## 11. Risks and decisions for the owner

Risks
- **Recall loss from tighter selection (A1, A2).** Covered by the replay gate and by keeping the wide profile when confidence is medium.
- **Agent behaviour changes when the layout changes (A4).** Pilot on a live host before making it default.
- **Host behaviour moves between Claude Code versions (C1, C2).** Reports of hook features being ignored exist; ship canaries in `prism doctor` and fall back to documented behaviour.
- **Replay is a proxy.** Commit subjects are poor queries and the audit used a HEAD index. Fix in the real harness by indexing the parent commit, and do not quote replay numbers as agent savings.
- **Single-repository, vendor-run evidence** for several external claims (section 9). They set direction only.

Decisions needed
1. Is a 2-point file-recall tolerance acceptable in exchange for the precision gain (A1, A2)?
2. Should an install with the hook leave MCP off by default (C4)?
3. How to split `CLAUDE.md`: which sections become `docs/spec/` and which become path-scoped rules (F1).
4. Which hosts get the live pilot first: Claude Code, Codex, or Antigravity?
5. Is a model that needs `trust_remote_code` acceptable if vendored and pinned (E2), or is it ruled out?

---

## Appendix — replay script used in the audit

Needs `prism` on PATH and an indexed checkout. Saved here so D2 can start from it. Known limits: it indexes HEAD, not each commit's parent, and uses the subject line as the query.

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
