# PRISM: research and implementation priorities for token efficiency

Research date: 10 October 2026. This is a broad, targeted review of primary documentation, research papers, implementations and two first-hand community reports. It is not an exhaustive survey of every product. Recommendations are proposals, not measured PRISM improvements. No production code or benchmark configuration was changed during this research.

## Decision

Optimise total work per verified solution. The immediate priorities are delivery reliability, task-aware ranking, sufficient exact source, and measurement. Add semantic retrieval selectively. Treat history compression and provider caching as host integrations, not capabilities an MCP server automatically possesses.

PRISM's existing context-engine documentation already describes AST/source retrieval, graph expansion, source-hash checks, session-aware delivery, lean MCP tools and adaptive preflight budgets. ADR 0004 documents an explicit output-filter wrapper. Extend and evaluate these mechanisms instead of treating them as missing. These are documented capabilities; this research is not a fresh implementation audit.

Local references: [context engine](../context-engine.md), [output filtering](../adr/0004-output-filtering.md), [benchmark protocol](../benchmarks/protocol.md).

## 1. Define the objective before optimising

Track separate quantities:

| Quantity | Meaning | What changes it |
|---|---|---|
| Packet tokens | One PRISM response | Selection, formatting, budgets |
| Processed input | Sum of provider input across model requests, cache reads counted once | Context size and number of requests |
| Fresh input | Input not served from cache, with provider-specific write categories identified | Cache behaviour and new context |
| Output | Generated output; do not add a reported reasoning subset twice | Reasoning, tool arguments, patch size, prose |
| Cost | Actual provider charges, or an explicitly labelled price estimate | Input/output/cache rates and extra services |
| Tokens per verified success | All assigned attempts' tokens divided by verified successes | Correctness, retries and total work |
| Latency | Retrieval, indexing, model, tools and verification separately | Local implementation and agent trajectory |

For an illustrative append-only session with fixed overhead H, initial evidence P, average growth d, and n requests:

`processed input approximately n(H + P) + d*n*(n-1)/2`

This is an explanatory model, not an empirical estimate. It shows why an additional turn can cost more than a somewhat larger initial packet. Caching changes the price of repeated input; it does not make those tokens disappear from processed-input accounting. Current OpenAI documentation also distinguishes cache writes and lookup boundaries: stable text alone does not guarantee a hit. [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

Example: increasing initial evidence by 800 tokens for five requests adds approximately 4,000 processed tokens. If it avoids one later 25,000-token request, the net can be favourable. The real comparison must include effects on subsequent context, output and success.

## 2. Evidence and implications

### A. Tool interfaces can remove entire reasoning steps

SWE-agent studies the agent-computer interface as a determinant of software-engineering performance. Anthropic recommends tools with clear purposes, bounded outputs and evaluation against actual tasks. This supports designing a high-level retrieval operation that performs local search, symbol resolution and evidence selection without asking the model to orchestrate each step. [SWE-agent](https://arxiv.org/abs/2405.15793); [Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents).

**PRISM proposal:** keep one obvious initial operation, with host-specific instructions that name the available transport. Return a single usable packet. Record availability, invocation, success and delivery separately. An attempted unavailable CLI command must not count as successful MCP use. Test installed behaviour in fresh host sessions, not just direct Python function calls.

### B. Small tool catalogues and large catalogues need different strategies

Anthropic's advanced-tool-use article reports large reductions in loaded tool definitions using deferred discovery. It explicitly says discovery adds a step and is less useful for small tool libraries. Its 85% example concerns tool/context overhead in that setup, not universal end-to-end coding savings. [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use).

**PRISM proposal:** retain a small default tool profile. Do not add a mandatory discovery round for a handful of compact tools. Make specialised analysis tools optional or host-deferred. Measure actual model-visible schema size and delivery turns, not only server output bytes.

### C. Combine exact and semantic retrieval

Cursor reports improved codebase-question accuracy from semantic search alongside grep, and describes training retrieval from agent traces. The reported accuracy improvement is not a token-saving percentage. Anthropic's contextual retrieval combines lexical and embedding retrieval with chunk context and reranking; its retrieval-failure improvements were measured on its datasets, not PRISM edits. [Cursor semantic search](https://cursor.com/blog/semsearch); [Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval).

**PRISM proposal:** use the existing lexical/symbol engine for exact paths, identifiers and literals. Add an optional local semantic candidate channel for behavioural descriptions and vocabulary mismatch. Merge candidate rankings, then apply task-specific evidence rules. Reciprocal rank fusion is a practical baseline because it combines ranks from distinct scoring systems. It does not require introducing Elasticsearch into PRISM. [RRF reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).

Do not pay an LLM to rewrite every query or summarise every source file by default. Start with deterministic chunk metadata: path, qualified symbol, enclosing class, signature and existing docstring. Evaluate optional embeddings and rerankers on held-out tasks, including local compute, refresh latency and memory.

### D. Distinguish the requested change from incidental matches

The Flask JSON trace retrieved an existing `PurePath` use in package discovery before the serializer implementation. Exact matching was useful evidence about occurrences but a poor proxy for edit relevance.

**PRISM proposal:** extract separate task roles: target subsystem, requested behaviour, existing identifier/value, new identifier/value, and constraints. For an addition, a new type's existing occurrences are secondary candidates; for a rename or replacement, old occurrences are central. For bug fixes, prioritise stack frames and owning functions. These are proposed ranking features, not rules that establish relevance with certainty.

A small deterministic classifier can be the first experiment. Keep ambiguous queries on a general path; do not introduce another remote model call merely to choose a retrieval strategy.

### E. Graphs should select a useful neighbourhood

Aider documents a budgeted repository map of key symbols and signatures selected using dependency-graph ranking, with size adjusted to conversation state. Serena demonstrates symbol-level navigation and references backed by language servers. These are implementation references; their existence does not establish a PRISM savings percentage. [Aider repository map](https://aider.chat/docs/repomap.html); [Serena](https://github.com/oraios/serena).

**PRISM proposal:** use request-conditioned graph expansion around likely implementation sites. Prefer the called helper, owning configuration, direct contract and relevant test over globally popular nodes. Bound fan-out. Label uncertain dynamic edges. Consider an optional LSP backend only for languages or tasks where the current resolver demonstrably misses useful relationships; keep the lightweight path available.

### F. Relevant context can still be insufficient

Google's sufficient-context research distinguishes failure to supply enough evidence from failure to use evidence. Anthropic describes both up-front retrieval and just-in-time exploration, with a task-dependent trade-off. [Sufficient Context](https://research.google/pubs/sufficient-context-a-new-lens-on-retrieval-augmented-generation-systems/); [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

**PRISM proposal:** assess edit evidence separately from match completeness. An exhaustive list of a literal does not establish every required behavioural change. Prefer a complete small implementation plus required imports/contracts over partial excerpts from several candidates. Supply precise recovery ranges when necessary. Avoid calling a packet universally “edit-ready” based only on literal coverage.

For Flask JSON, the desired packet would include `_default`, the relevant imports, the provider's supported-types documentation, and a compact test pointer. Whether this changes success or turns must be measured.

### G. Select complete source; do not paraphrase edit anchors

LLMLingua explores learned prompt compression. It is a useful experiment for prose, but its results do not establish that compressed executable source remains safe for exact-match editing. Older long-context research also shows sensitivity to where useful information appears; it is motivation for evaluating packet ordering, not a guarantee for current models. [LLMLingua](https://github.com/microsoft/LLMLingua); [Lost in the Middle](https://arxiv.org/abs/2307.03172).

**PRISM proposal:** compress through selection first. Preserve identifiers, whitespace, literals and source text within delivered edit ranges. Merge overlaps, remove duplicate ranges and shorten wrappers. Put the primary implementation before incidental matches. Keep paths, line ranges and freshness information. Preserve raw logs and diffs for recovery.

### H. Filter before data enters model history

RTK is a useful reference for deterministic command-output filtering. Its README explicitly distinguishes reducing shell-output volume from reducing the overall bill. Anthropic's code-execution pattern similarly filters and aggregates tool results locally before exposing them to the model. [RTK](https://github.com/rtk-ai/rtk); [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp).

**PRISM proposal:** evaluate the existing opt-in filter on noisy successful test/build output. Preserve exit codes, failure sections, useful diagnostics and a raw-output pointer. Fail open for unsupported formats. Do not silently rewrite or auto-approve commands. Test output filtering separately from retrieval so each contribution is visible.

Run deterministic local passes in one PRISM invocation. Introducing a general-purpose code-execution service solely for retrieval would add complexity PRISM may not need.

### I. History reduction requires host cooperation

The Complexity Trap compares observation masking and LLM summarisation within agent scaffolds and finds simple masking competitive in its tested settings. This is evidence for experimentation, not a transferable “half-price PRISM” claim. [The Complexity Trap](https://arxiv.org/abs/2508.21433).

**PRISM proposal:** retain versioned task notes and delivered-range state, but distinguish storage from what the host model still sees. A compaction or new context may invalidate the assumption that earlier source is available. Let adapters signal a context epoch; provide a bounded rehydration path when the host lacks that signal. Do not suppress necessary source solely because it was once sent.

An MCP server cannot normally delete earlier host messages. Observation masking, cache breakpoints and compaction policy belong in a host adapter or agent harness. Evaluate these independently of core retrieval.

### J. Avoid unnecessary agent complexity

Agentless is an example of a simpler localisation/repair/validation pipeline that performed competitively in its historical evaluation. Its historical scores should not be treated as present-day model comparisons. [Agentless](https://arxiv.org/abs/2407.01489).

**PRISM proposal:** keep deterministic planning inside retrieval where possible. Do not introduce multi-agent discovery, repeated remote planning, a global narrative generator or learned compression merely because those designs are available. Promote each only when an ablation shows lower total work at acceptable correctness.

## 3. Proposed task policy

The budget values below are experimental starting points, not validated defaults or guaranteed limits. Use the host/model tokenizer where available; label fallback estimates. Count the complete rendered packet including wrappers.

| Task condition | Initial evidence policy | Experimental budget |
|---|---|---:|
| Explicit path and known symbol | Direct exact source, required local definitions | 400–900 tokens |
| Small edit in an identified subsystem | Complete main implementation and contract | 900–1,800 |
| Architecture question | Connected signatures and flow map, source only where needed | 700–1,500 |
| Behavioural query with weak lexical evidence | Hybrid candidates, rerank locally, bounded expansion | 1,500–3,000 |
| Cross-file behaviour change | Required sites, dependencies and test pointers | 2,000–4,000 |
| Still insufficient under cap | Honest limitation and batched exact recovery ranges | Explicit cap |

Respect explicit user caps. A cheap direct-read path and a no-injection path are valid outcomes when retrieval is unlikely to avoid work. Do not always fill the available budget. Benchmark budget curves rather than selecting a globally smaller number by intuition.

Proposed packet order:

1. Target and reason for selecting it.
2. Exact primary implementation, required helpers and import context.
3. Directly affected contract/documentation and focused test pointer.
4. Coverage, skipped areas and unresolved ambiguity.
5. Optional graph evidence and precise recovery ranges.

The packet should make the next useful action obvious without claiming that retrieval verifies the solution.

## 4. Implementation order and acceptance evidence

| Priority | Work | Evidence required before claiming improvement |
|---|---|---|
| P0 | Transport-specific instructions and delivery telemetry | Fresh installed-host checks identify actual MCP calls, failed CLI attempts and one-time hook delivery |
| P0 | Stable accounting and report vocabulary | Hand-reconcile provider events; cache categories counted once; missing usage remains unknown |
| P0 | Addition/rename/bug-fix task roles | Held-out examples separate new symbols from old edit targets; Flask regression reproduced offline |
| P0 | Complete main implementation under budget | Required-source coverage improves without worse task correctness; fewer follow-up reads |
| P1 | Task-dependent budget and direct-read path | Paired live trials show lower processed input per success; easy tasks do not regress systematically |
| P1 | Optional semantic candidate channel and fusion | Higher held-out recall of true edit sites; acceptable local latency and end-to-end improvement |
| P1 | Trace dataset and ranking feedback | Human/verified labels; train and evaluation repositories separated |
| P1 | Existing output-filter evaluation | No hidden failures in fixtures; full logs recoverable; live token contribution measured separately |
| P1 | Session/context-epoch integration | Retry, lost reply, compaction, reconnect and changed-file cases preserve source availability |
| P2 | LSP-backed references for weak languages | Better reference precision/recall on relevant tasks, accounting for startup cost |
| P2 | Local reranker or prose compression | Gains survive ablations including latency, memory, cache disruption and any model usage |
| P2 | Host history masking/cache controls | Host-supported implementation, full cost accounting and correctness checks |

Do not implement all rows at once. Start with P0 and preserve a versioned baseline.

## 5. Benchmark conditions that can answer the question

Anthropic recommends evaluating outcomes alongside full trajectories and separating grading from agent self-report. Its infrastructure study shows resource configuration can affect results. [Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents); [Infrastructure noise](https://www.anthropic.com/engineering/infrastructure-noise).

Use two complementary evaluations:

**Installed product:** retain all treatment failures, including unavailable tools, in the headline comparison. Measure whether users actually receive the intended benefit.

**Verified delivery diagnostic:** use a separately specified setup with confirmed transport and packet delivery to isolate retrieval. Never silently discard installation failures from the product result.

Suggested sequence:

1. Freeze current prompts, source, repository commits, model IDs/effort and host versions. Snapshot live result files before generating reports.
2. Create offline tasks with labelled implementation, required helper and irrelevant lookalike locations. Include new-feature additions, bug fixes, renames, architecture, config/docs and multi-file edits.
3. Replay retrieval without model calls. Measure true edit-site recall at the packet budget, required-source coverage, unnecessary-source volume, honest completeness and latency.
4. Run matched live sessions only after offline regressions pass. Keep normal search available in baseline; never force it to read the whole repository.
5. Randomise arm order within task/repetition blocks. Keep environment, resources, tools and verification scope equal apart from the declared treatment.
6. Use held-out repositories and newly authored or transformed tasks. Flask is an established public project; possible prior familiarity is a hypothesis to test, not proof of contamination. Public and held-out task separation is an established benchmark strategy. [SWE-Bench Pro](https://arxiv.org/abs/2509.16941).
7. Score patches with independent checks; architecture needs a semantic rubric, not only keywords. Keep failures, timeouts, retries and no-patch false success in accounting.
8. Report per-task and per-host results, uncertainty, success and tokens per success. Bootstrap at the task/repository level appropriate to the generalisation claim; repetitions alone do not create more independent tasks.
9. Choose sample size and a useful-effect target from pilot variance before confirmation. One observation cannot provide a meaningful uncertainty interval.
10. Freeze ranking before confirmation. A fix informed by a failed benchmark belongs in a new campaign, not the old result.

Record at minimum: model requests, successful PRISM delivery, failed tool calls, fallback searches, repeated source ranges, fresh/cache-write/cache-read/output tokens, patch outcome, elapsed time, index build/update time and any embedding/reranker/summariser usage. If a host's “turns” are user turns rather than model requests, label that difference explicitly.

For local embeddings/indexing, report CPU/GPU time, memory and disk separately. For remote enrichment, include its tokens and amortisation across real reuse. Do not hide index maintenance behind a zero-token retrieval label.

## 6. Community evidence and limits

### Community Wisdom: [We built a context system for our coding agents. They ignored it and used grep.](https://dev.to/kentkandiforge/we-built-a-context-system-for-our-coding-agents-they-ignored-it-and-used-grep-58pk)

> **Source:** [Kent Alstad](https://dev.to/kentkandiforge)
>
> **Tags:** `agents`, `buildstuff`, `agentskills`, `ai`
>
> The author reports poor retrieval adoption and misleading hypothetical savings, and recommends collecting real request-to-file evidence. In the comments, he says his earlier measurement could not establish the effect of renaming tools. Useful first-hand motivation for trace collection; not independent validation of PRISM.
>
> [Read Full Discussion](https://dev.to/kentkandiforge/we-built-a-context-system-for-our-coding-agents-they-ignored-it-and-used-grep-58pk).

### Community Wisdom: [Does compacting tool output lower a coding agent's API bill?](https://dev.to/projectescape/does-compacting-tool-output-lower-a-coding-agents-api-bill-ena)

> **Source:** [Aniket](https://dev.to/projectescape)
>
> **Tags:** `ai`, `llm`, `opensource`, `deepseek`
>
> The author reports an inconclusive cost improvement despite removing output, with cache economics and agent variation dominating. Earlier source summarisation caused edit failures. Exact prompts and raw sessions were not published, limiting reproducibility. In comments, the author also acknowledges insufficient evidence for long-session quality claims. Treat it as a caution and experimental lead, not a universal result.
>
> [Read Full Discussion](https://dev.to/projectescape/does-compacting-tool-output-lower-a-coding-agents-api-bill-ena).

The two accounts support measuring real trajectories and preserving exact edit source. They do not establish a broad community consensus or an expected savings percentage.

## 7. What this research does not establish

- No defensible universal 70–75% token-saving promise.
- No proof that embeddings always beat exact search, or that graphs always help.
- No proof that fewer packet tokens mean lower cost or higher correctness.
- No guarantee that a provider API feature is exposed by Codex, Claude Code or another host.
- No reason to disable verification or suppress legitimate fallback investigation to improve a score.
- No measured benefit from the proposals until PRISM passes its own offline and live comparisons.

The most useful next implementation is a small P0 change set that makes the intended evidence arrive, selects the correct implementation, and supplies enough exact source to avoid another discovery turn.
