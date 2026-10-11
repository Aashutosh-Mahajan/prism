# Deep research: making PRISM cheaper and more reliable (10 October 2026)

Second, wider pass after the three-host benchmark (Antigravity, Codex, Claude Code × 3 repetitions).
It extends `research-token-efficiency-2026-10-10.md`. Each area ends with **PRISM today → gap → action**.
Figures are the authors' own unless stated; vendor numbers are claims, not independent measurements.
"Measured here" means our own `results_*_r3.jsonl` and session logs.

## 1. How agents spend tokens

- Input tokens dominate; cached re-reads are the largest category; the same task varies up to **30×** between runs; more
  tokens do not mean higher accuracy, and accuracy often peaks at intermediate cost
  ([Bai et al., arXiv 2604.22750](https://arxiv.org/abs/2604.22750)). Models underestimate their own usage (correlation ≤ 0.39).
- Task specification matters: shrinking a full specification to a bare user story raised spend **29.7%**, with effects from 13% to
  115% by task, and run-to-run variance unchanged ([arXiv 2608.25399](https://arxiv.org/abs/2608.25399)).
- Language matters: agents spend far more tokens in OCaml, Rust and Java than in Python for the same problems
  ([Tokenmaxxing, arXiv 2607.22807](https://arxiv.org/abs/2607.22807)).
- Irrelevant context lowers reliability, not only cost: accuracy falls with input length and distractors
  ([Chroma, Context Rot](https://www.trychroma.com/research/context-rot)); one controlled coding-agent preprint saw pass rate fall from 80% to 30% with a long irrelevant context ([arXiv 2607.17937](https://arxiv.org/html/2607.17937v2)).

**PRISM today → gap → action.** PRISM turns a bare request into a fuller specification (exact sites, literals, tests), which is
consistent with the 29.7% finding and with our best task (age rule, −70 to −88% on Antigravity). Gap: the packet does not state
a *done condition*. Action: end each packet with an acceptance line ("done when `verify` reports no remaining sites and these tests pass").

## 2. Repository context files and standing context

- Repository overviews and generated context files did **not** help agents reach the right code faster and raised cost 20–23% with
  success changes within ±4% ([Gloaguen et al., arXiv 2602.11988](https://arxiv.org/abs/2602.11988)); a different study found
  −28.6% runtime and −16.6% output tokens with a context file, so results depend on what is measured.
- A *stale* convention file cost more than none, because agents follow it ([coherence-debt paper, arXiv 2608.16630](https://arxiv.org/html/2608.16630v1)).
- Codex stops reading AGENTS.md at 32 KiB by default (`project_doc_max_bytes`) ([overview](https://codex.danielvaughan.com/2026/03/26/agents-md-advanced-patterns/)).

**PRISM today → gap → action.** PRISM already injects a compact brief and a ~120-token block, not an overview. Action: keep it that way;
add a `prism doctor` check that flags a managed block or brief older than the running engine; never generate narrative by default.

## 3. Retrieval and localization research

| Work | Result | Relevance |
|---|---|---|
| [Agentless](https://huggingface.co/papers/2407.01489) | fixed localize→repair pipeline matched agent frameworks at $0.34–0.70 per issue | localization is the cost lever |
| [LocAgent](https://aclanthology.org/2025.acl-long.426.pdf) | graph-guided localization, 77.7% file-level Acc@1; −80% cost ($0.66 → $0.09) in its own benchmark | graph of files, classes, functions with import/call/invoke edges: PRISM has this |
| RepoGraph (ICLR 2025) | ego-graph around search terms; +32.8% relative on SWE-bench (secondary) | packet "callers/calls" is this idea; ring-ordering could improve ranking |
| [SHERLOC](https://arxiv.org/html/2606.24820) | separate localizer: −36.7% localization tokens, −23.1% total, resolve rate up | the packet is the localizer; measure it that way |
| [Codebase-Memory](https://arxiv.org/abs/2603.27277) | tree-sitter graph via MCP: ~10× fewer tokens, 2.1× fewer tool calls, but answer quality 83% vs 92% for file exploration | **graph tools trade accuracy for tokens**; PRISM must report pass rate beside tokens (we do) |
| [Cursor semantic search](https://cursor.com/blog/semsearch) | semantic + grep beats grep alone, +12.5% accuracy (6.5–23.5% by model) | PRISM's optional semantic channel is unmeasured |
| [Sourcegraph Cody](https://arxiv.org/pdf/2408.05344) | BM25 + embeddings: −35% top-20 retrieval failures | hybrid ranking has a documented gain |
| [Augment Context Engine](https://www.augmentcode.com/blog/context-engine-mcp-now-live) | vendor-run: +70% quality, fewer tokens and turns on 300 PRs of one repository | direction agrees; single-repo, vendor-run |

**PRISM today → gap → action.** Lexical + literal + graph retrieval is in place. Gaps: (a) semantic blending is optional and never measured;
(b) "explain the architecture" requests get a silent hook (low confidence). Action: evaluate `[semantic]` on a labelled set of vague requests, make the
overview packet confident enough for the hook to speak, and keep reporting accuracy next to tokens.

## 4. Agent–computer interface (what the tool returns)

- SWE-agent's interface study: concise feedback, few actions, built-in linting; showing too little (30 lines) or the whole file both
  scored below a 100-line window; removing the linter cost ~3 points ([paper](https://arxiv.org/abs/2405.15793)).
- Tool responses should be paginated, filtered and have sensible defaults; truncation messages should steer toward narrower calls; offer a concise and a detailed format
  ([Anthropic, Writing tools for agents](https://modelcontextprotocol.info/docs/tutorials/writing-effective-tools/)). Claude Code caps tool responses at 25,000 tokens.
- Compact notations (TOON/TRON) save up to 18–27% only on large uniform tables, can break multi-turn and parallel tool calls, and the effect depends on the model
  ([Notation Matters, arXiv 2605.29676](https://arxiv.org/abs/2605.29676)).

**PRISM today → gap → action.** Packets are budgeted and grouped by file, with a `Next:` line. Gaps: no concise/detailed switch; no lint-style guard on diffs it proposes.
Action: a `--detail brief|full` mode (brief = sites only, ≈ 40% smaller); validate any generated diff with `git apply --check` before printing; do **not** adopt exotic notations.

## 5. Making agents use the tool

- Agents often skip MCP tools even with explicit CLAUDE.md rules; enforcement by hooks works better than prose; one-line tool descriptions decide choice
  ([claude-code #47565](https://github.com/anthropics/claude-code/issues/47565), [RoslynMcp #99](https://github.com/MadQ/RoslynMcp/issues/99)). Matches our data (plain CLI +6% on Codex, −4% on Claude Code).
- MCP tool definitions are deferred/lazy in Claude Code and Codex; Anthropic's tool-search and programmatic tool calling cut definition overhead (up to ~85%, secondary) and keep intermediate results out of context
  ([Anthropic advanced tool use](https://anthropic.com/engineering/advanced-tool-use)).
- A PreToolUse hook can **deny** a redundant read of an unchanged file with a steering hint (cache expiry 20 min, kill switch) ([read-once](https://dev.to/boucle2026/read-once-a-claude-code-hook-that-stops-redundant-file-reads-4bjk)). A deny never approves anything, so it does not change the permission model.

**PRISM today → gap → action.** The prompt hook delivers the packet, which is the reliable path. Action: an opt-in `prism hook dedupe-read` (Claude Code PreToolUse, deny-only): block re-reads of unchanged files and broad searches
already answered by an "exhaustive" list; measure before enabling by default.

## 6. Cutting calls and context (generic techniques)

- Observation masking halves cost and matches LLM summarisation ([Complexity Trap](https://huggingface.co/papers/2508.21433)); trajectory reduction −39.9% to −59.7% input tokens ([AgentDiet](https://arxiv.org/abs/2509.23586)); context editing −84% on a 100-turn test ([Anthropic](https://claude.com/blog/context-management)); cache-aware eviction −56% to −87% ([TokenPilot](https://arxiv.org/abs/2606.17016)); query-aware line pruning −23% to −54% ([SWE-Pruner](https://arxiv.org/abs/2601.16746)).
- Parallel tool calls and RL search subagents (8 parallel calls, ≤ 4 turns) cut turns; [Cognition](https://cognition.com/blog/swe-grep), [Morph](https://www.morphllm.com/comparisons/swe-grep-vs-warpgrep) (vendor figures).
- Diff and batched-edit formats are far cheaper than whole-file output ([Aider](https://aider.chat/docs/leaderboards/notes.html)); Claude Code requires a Read before Edit ([tools reference](https://code.claude.com/docs/en/tools-reference)).
- Routing exploration to a cheaper model (Explore subagent on Haiku 5.5) isolates exploration tokens ([guide](https://www.developersdigest.tech/blog/claude-code-subagent-model-haiku-explore-2026)); delegation overhead can erase the gain on small tasks.
- Codex: compaction replaces the cached prefix; each retry re-sends full context; `model_reasoning_effort` and `model_verbosity` are cost levers ([tips](https://codex.danielvaughan.com/2026/04/08/codex-cli-performance-optimization/)). Gemini CLI caching applies with API-key authentication, 4,096-token minimum on newer Flash models ([Gemini CLI docs](https://google-gemini.github.io/gemini-cli/docs/cli/token-caching.html)).

**Measured here (Claude Code, edit tasks):** 25.4 model calls without PRISM, 18–20 with it; search/read calls 9.6 → 5–7; edit calls unchanged at ~5–6; ~21k fixed tokens per call; the injected packet adds ~8k to the first call and is re-sent every call.

**Action.** Packet batching line and diff for mechanical changes (plan 7.3, 7.4); deliver packets as clearable tool results where the host clears them (7.7); document Explore-on-cheap-model, Codex effort/verbosity, Gemini API-key caching in `docs/integrations.md` (no code).

## 7. Verification and tests

- Agents run too many tests; a narrow trustworthy set speeds self-verification. Anthropic scaled test impact analysis for agent-driven CI
  ([Anthropic](https://claude.com/blog/agentic-coding-is-straining-ci-heres-how-we-scaled-test-impact-analysis-at-anthropic)); TDAD (AST code–test graph + weighted impact) reports 70% fewer regressions ([arXiv 2603.17973](https://arxiv.org/abs/2603.17973));
  pytest-testmon selects tests by coverage but silently turns off with some selectors and misses files outside its tracked tree ([testmon](https://github.com/tarpas/pytest-testmon)).

**PRISM today → gap → action.** The packet prints `Run: <command> <files>` from the call graph. Gap: no weighting, and it can list nothing. Action: weight tests by call-graph distance, always return at least the nearest test directory, and warn when a selector would run zero tests.

## 8. Indexing speed

- Zoekt: trigram index, per-repo reindex; SCIP replaced LSIF (smaller, faster); stack graphs resolve cross-file names but are memory-heavy ([Zoekt](https://github.com/sourcegraph/zoekt)). No source measures millisecond latency at scale.

**PRISM today → gap → action.** Postings are SQLite; warm queries are ~0.04 s server-side and 0.5–0.8 s end to end, dominated by Python start-up. Action: none needed for retrieval; keep the warm process; consider a compiled launcher only if latency becomes a blocker.

## 9. Evaluation method (how to trust our numbers)

- Repeats of one configuration vary more than differences between configurations; detecting a 2-point gain needs ~9 runs and a 1-point gain ~36
  ([Identical Runs, Different Results, arXiv 2609.33812](https://arxiv.org/html/2609.33812)). Report pass^k beside pass@1, tokens per solved task, and cost/accuracy Pareto ([HAL](https://hal.cs.princeton.edu/scicode)).
- Harness choice is a hidden variable ([Scaffold Effect, arXiv 2607.22585](https://arxiv.org/html/2607.22585v1)); evaluate management policies on held-out tasks ([Measure Before You Manage](https://arxiv.org/abs/2608.31057)).

**Action.** Our 3 repetitions detect only large effects (we saw plain CLI move from −23% to +6% between 1 and 3 repetitions). Next rounds: ≥ 5 repetitions, tokens per solved task, pass^k, bootstrap intervals, and at least two more repositories (one Java/Go, one TypeScript).

## 10. Findings that change priorities

1. The main failure is a **correctness gap** (twin definitions), not retrieval: fix first.
2. **Delivery beats retrieval**: the hook is the only setup that reliably changed behaviour; plain CLI/MCP depend on the agent.
3. **Call count, not packet quality, is now the cost driver**: batching and one-shot diffs are the only levers that remove edit calls.
4. **Packet size is a real cost** (re-sent every call, and irrelevant context lowers reliability): smaller, de-noised, clearable.
5. **Graph tools can cost accuracy** (83% vs 92% in one study): keep reporting pass rate; the verify gate is the safety net.
6. **Do not add**: LLM summarisation, exotic notations, model-based compression.
