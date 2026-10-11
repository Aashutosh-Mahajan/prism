# Token efficiency for coding agents: research and what PRISM should adopt (10 October 2026)

Question: what do other tools and papers do to make coding agents cheaper, how much do they claim,
and which of it fits PRISM (local, offline, deterministic, never edits user code) so the benchmark
result moves toward the 70–75% target?

Numbers below are **as reported by their authors** unless marked "measured here". Vendor figures are
not independent. Each item ends with how it maps to PRISM and what we expect.

## 0. Where the tokens go (the model everything else hangs on)

- Input tokens dominate agent cost, and **cache reads are the largest category**: the same context is re-sent
  on every model call ([How Do AI Agents Spend Your Money?, arXiv 2604.22750](https://arxiv.org/pdf/2604.22750)).
  Agentic coding uses orders of magnitude more tokens than chat, and repeated runs of one task vary by up to 30×.
- Read-type operations are reported as 76% of tokens in one SWE-bench trace study, and code fetched early stays in
  context and is paid for again on every later call ([summary](https://www.augmentcode.com/guides/ai-coding-cost-analysis-agent-token-spend)).
- **Measured here (Claude Code, Haiku 5.5, 3 repetitions):** about 21k tokens of fixed context per model call;
  25 model calls per edit session without PRISM, 18–20 with it; PRISM removes mostly search/read calls
  (9.6 → 5–7 per session) but the 5–6 edit calls and the post-edit checks stay.

So cost ≈ (number of model calls) × (fixed context + accumulated history). There are only two levers:
**fewer calls** and **less context per call**.

## 1. Fewer model calls (largest lever)

| Idea | Evidence | PRISM mapping | Expected effect |
|---|---|---|---|
| **Parallel tool calls in one turn.** Models can issue independent calls together; dependent calls need separate turns ([Anthropic docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)). RL-trained search subagents do up to 8 parallel searches in at most 4 turns; >60% of an agent's first turn is retrieval ([SWE-grep](https://cognition.com/blog/swe-grep)). Morph reports 3.8 steps vs 12.4 for the same retrieval quality ([WarpGrep](https://www.morphllm.com/comparisons/swe-grep-vs-warpgrep), vendor). | Today our sessions show ~20 tool calls in ~18–25 model calls, i.e. almost no batching. Packets should end with a batching instruction: "read these N files in one turn; edit all N in one turn." | −20–35% of calls on multi-file tasks. Cheap to try: one line in the packet and the instruction block. |
| **Ship the change as a diff, not N edits.** Diff formats are far cheaper than whole-file output ([Aider notes](https://aider.chat/docs/leaderboards/notes.html)); MultiEdit batches edits into one atomic call ([guide](https://dev.to/jsmanifest/claude-code-batch-file-edits-using-multiedit-and-write-together-to-cut-round-trips-in-long-5cpd)); apply-patch tools take structured diffs ([OpenAI](https://developers.openai.com/api/docs/guides/tools-apply-patch)). Claude Code needs a prior Read before Edit, so each edited file costs Read + Edit ([tools reference](https://code.claude.com/docs/en/tools-reference)). | For mechanical changes (old value → new value at known sites) PRISM prints a unified diff; the agent applies it with one `git apply`. PRISM only generates text, it never edits code. | Age task: ~30 calls → ~6. Largest single win; limited to mechanical edits. |
| **Localize first, repair second.** Agentless's fixed localize→repair pipeline matched agent frameworks at a fraction of the cost ([paper](https://huggingface.co/papers/2407.01489)); a separate localizer cut localization tokens 36.7% and total tokens 23.1% while raising resolve rate ([SHERLOC](https://arxiv.org/html/2606.24820)). | The packet is already a localizer. Add ranked edit sites with a reason, drop out-of-scope blocks (`archive/`, frontend when the request says backend). | Fewer wrong turns; also the fix for the biggest failure (below). |
| **A one-call search tool for the gaps.** RL search subagents exist because N sequential greps are slow and costly. | `prism find` runs several patterns/globs in one call and returns grouped, budgeted results. | Replaces 3–8 sequential searches when the packet is insufficient. |

## 2. Less context per call

| Idea | Evidence | PRISM mapping | Expected effect |
|---|---|---|---|
| **Observation masking.** Hiding old tool outputs behind a placeholder halves cost and matches LLM summarisation ([The Complexity Trap](https://huggingface.co/papers/2508.21433)). Anthropic's context editing (clearing stale tool results) reports −84% tokens on a 100-turn evaluation ([Anthropic](https://claude.com/blog/context-management)). Trajectory reduction cut input tokens 39.9–59.7% with success within ±2% ([AgentDiet](https://arxiv.org/abs/2509.23586)). | The host does this, not PRISM. What PRISM controls: how it enters context. A hook-injected packet is a persistent user message and cannot be cleared; a tool result can. So deliver by tool result where the host supports clearing, and keep packets small. | Removes PRISM's own accumulating cost (~60k tokens per session measured here). |
| **Query-aware pruning of what the agent reads.** SWE-Pruner filters file reads to the relevant lines: 23–54% fewer tokens on agent tasks ([paper](https://arxiv.org/abs/2601.16746)). | The packet already holds the relevant lines. Add exact `Read(file, offset, limit)` hints so agents do not read whole locale files (1,700 lines). Claude Code may not accept a partial read as "read before edit" for some models, so this needs a test on the target model. | Up to −20–30% where big files are read whole. |
| **Lazy tool and skill loading.** Cursor reports −46.9% total tokens for runs using MCP tools after moving tool descriptions to files ([Cursor](https://cursor.com/blog/dynamic-context-discovery)); Copilot reports −11% (per turn) and −18% (per user) with deferred tool loading ([VS Code](https://code.visualstudio.com/blogs/2026/06/17/improving-token-efficiency-in-github-copilot)). | PRISM's MCP schema is already one tool. Install only the `prism-context` skill by default (audit, refresh, decisions load on request). Measure what the skill list costs per call. | A few percent of fixed context. |
| **Cache-aware text.** Deliberate cache breakpoints reach a ~94% hit rate on agent workloads; longer retention helps when gaps exceed 10 minutes ([VS Code](https://code.visualstudio.com/blogs/2026/06/17/improving-token-efficiency-in-github-copilot)). | Hook header is already byte-stable; keep variable text last. | Small. |
| **Long outputs to files.** Cursor writes long tool output to a file the agent can `tail`/grep. | `prism filter` already tees full output. | Done. |

## 3. Correctness (failures cost tokens too)

- **Twin definitions.** The WEBP task failed in 21 of the 22 failing sessions (all hosts, all setups) because the same function exists in two files
  and the agent changed one (measured here, all hosts). Clone detectors (PMD CPD, jscpd) show how: hash a normalised
  body and group equal functions. PRISM should add a line "same function defined in N files; change all" to any packet
  whose target has twins. This is the biggest pass-rate fix and also saves the discovery calls.
- **Verify gate.** Already built (`prism hook stop`), currently Antigravity only; extend to Claude Code `Stop` and Codex.

## 4. What does not transfer

- LLM-based compression (LLMLingua-style, summarising reflectors) needs a model call; PRISM's core rule is no LLM.
- RL-trained search subagents are separate models; PRISM stays deterministic and offers the one-call `prism find` instead.
- Fast-apply merge models: not needed if PRISM supplies exact diffs.

## 5. Ceiling, honestly

With ~21k fixed tokens per call, Claude Code needs at least: 1 call to receive the packet, 1 to apply the change, 1 to check,
1 to answer ≈ 4–6 calls. Baseline is ~25. So the best case on Claude edit tasks is roughly −60–75% total,
**only if** batching and diffs work. On Codex the baseline is already 4–10 calls (~100–350k tokens per task),
so the best case is lower (−45–55%); small tasks (one-site edits) cannot reach 70% on any host.

## 6. Proposed order (cheapest and most informative first)

1. Twin-definition line + de-noise packet blocks (correctness; cheap).
2. Batching instruction in the packet (one line; measure calls per session).
3. `prism diff` / diff-bearing packets for mechanical changes.
4. `prism find` multi-pattern search.
5. Read-range hints (after a test of what Claude Code accepts as "read before edit").
6. Packet delivery as clearable tool results where supported; install only `prism-context` by default.
7. Extend the verify gate to Claude Code and Codex.
8. Re-run the 3-host × 3-repetition benchmark (and the other two repositories) to measure each step.

Sources are linked inline. Treat vendor numbers (Cursor, Morph, Copilot, Anthropic) as claims; the "measured here" rows
are from `results_*_r3.jsonl` and the Claude Code session logs.
