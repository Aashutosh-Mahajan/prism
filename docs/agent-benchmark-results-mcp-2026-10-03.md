# Codex agent benchmark using MCP — 2026-10-03

Six fresh Codex subagents completed 12 reports each, in three paired runs. All used `gpt-6.1-sol` with `medium` reasoning effort.

PRISM changed average tool output by **-8.6%**, total input processed by **+17.2%**, and completion time by **+18.8%**. Mean primary-function scores were **9.33/12 with PRISM** and **8.67/12 without**.

These are measured agent runs. The separate modelled estimate below is not a substitute for them.

## Measured results

| Run | Agent | Model turns | Tool calls | Input processed | Billable proxy | Work context | Tool output estimate | Seconds | Correct /12 | Partial | Tasks naming backend tests |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | without | 11 | 10 | 616,192 | 116,224 | 51,378 | 45,911 | 187.3 | 8 | 4 | 9 |
| 1 | with | 12 | 11 | 633,425 | 104,427 | 41,545 | 40,300 | 253.8 | 9 | 3 | 6 |
| 2 | without | 10 | 9 | 519,253 | 97,160 | 47,002 | 41,857 | 172.3 | 9 | 3 | 9 |
| 2 | with | 13 | 12 | 704,787 | 112,429 | 42,350 | 42,040 | 189.2 | 10 | 2 | 6 |
| 3 | without | 13 | 12 | 815,901 | 135,184 | 55,555 | 52,561 | 226.4 | 9 | 3 | 9 |
| 3 | with | 17 | 16 | 949,143 | 142,743 | 48,102 | 45,876 | 253.2 | 9 | 3 | 8 |
| **Mean** | **without** | 11.3 | 10.3 | 650,448.7 | 116,189.3 | 51,311.7 | 46,776.3 | 195.3 | 8.7 | 3.3 | 9.0 |
| **Mean** | **with** | 14.0 | 13.0 | 762,451.7 | 119,866.3 | 43,999.0 | 42,738.7 | 232.1 | 9.3 | 2.7 | 6.7 |

## MCP protocol evidence

PRISM was not registered as a native Codex tool in this chat. Each PRISM agent imported a small adapter through the persistent Node tool, started the real PRISM MCP server once, and invoked its tools using MCP JSON-RPC over stdio. The server retained its index between calls. Agents did not invoke the PRISM CLI or call navigator library functions directly. Protocol logs independently record every request and response. This is a genuine MCP transport run with an adapter, not a native registered-tool run.

The adapter returned one structured response representation, avoiding duplicate text and JSON copies. Source range reads remained ordinary file reads. Adapter startup, schema discovery, calls and shutdown were part of the timed agent sessions; the controller's separate smoke test was excluded.

| Run | Server starts | MCP tool calls | Responses | RPC errors | Tool errors | Navigation errors | PRISM CLI command sites |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 65 | 65 | 0 | 0 | 2 | 0 |
| 2 | 1 | 63 | 63 | 0 | 0 | 0 | 0 |
| 3 | 1 | 84 | 84 | 0 | 0 | 0 | 0 |

Navigation errors are structured PRISM responses such as `not_found`; agents can recover with another query. Exact error codes are retained in metrics.json. Every client closed and every server exited.

Per-tool request counts:

| Run | Brief | Search | Locate | Context | Impact | Module | Status |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 22 | 0 | 30 | 12 | 0 | 0 |
| 2 | 1 | 20 | 0 | 29 | 13 | 0 | 0 |
| 3 | 1 | 36 | 4 | 31 | 12 | 0 | 0 |

## Comparison with the earlier CLI run

Each column is an average of three agents. The MCP baseline was rerun rather than reused. This is an observational comparison: fresh agent decisions, timing, setup prompts, JSON output and adapter overhead can differ, so any change cannot be attributed solely to transport.

| Metric | Earlier CLI with PRISM | New MCP with PRISM | Earlier baseline | New baseline |
|---|---:|---:|---:|---:|
| model_turns | 12.3 | 14.0 | 9.7 | 11.3 |
| tool_output_tokens_est | 33,560.3 | 42,738.7 | 51,481.0 | 46,776.3 |
| total_input_processed | 577,739.0 | 762,451.7 | 586,755.3 | 650,448.7 |
| work_context | 36,537.7 | 43,999.0 | 56,361.0 | 51,311.7 |
| billable_input_equiv_proxy | 94,168.0 | 119,866.3 | 114,243.3 | 116,189.3 |
| duration_seconds | 267.2 | 232.1 | 187.8 | 195.3 |
| correct | 9.7 | 9.3 | 9.0 | 8.7 |

## Per-task scoring

C = correct primary; P = expected function appears as a dependent; W = neither. The supplied alternatives for tasks 5, 6 and 8 were retained. No alternatives were added after seeing results.

| Task | Run 1 without | Run 1 with | Run 2 without | Run 2 with | Run 3 without | Run 3 with |
|---|---|---|---|---|---|---|
| 1 | C | C | C | C | C | C |
| 2 | C | C | C | C | C | C |
| 3 | C | C | C | C | C | C |
| 4 | P | C | C | C | C | C |
| 5 | C | C | C | C | C | C |
| 6 | C | C | C | C | C | C |
| 7 | C | C | C | C | C | C |
| 8 | C | C | C | C | C | C |
| 9 | P | P | P | C | P | P |
| 10 | C | C | C | C | C | C |
| 11 | P | P | P | P | P | P |
| 12 | P | P | P | P | P | P |

## Direct caller mentions

Across the 12 target functions, the current index lists 76 direct callers. Counts below use textual name matching; full per-task caller lists and matches are retained in scores.json.

| Run | Without PRISM | With PRISM |
|---|---:|---:|
| 1 | 24 / 76 | 43 / 76 |
| 2 | 30 / 76 | 39 / 76 |
| 3 | 16 / 76 | 40 / 76 |
| **Mean** | 23.3 / 76 | 40.7 / 76 |

## Protocol and interpretation

Platforma currently indexes 351 files and 60,200 lines. Each repetition used two identical fresh source copies; only the PRISM side was indexed. The consent registry was isolated per repetition. Agents received bug reports, not target names or the answer key, and had fresh histories. Both sides of each pair ran concurrently. Pair starts were dispatched sequentially within seconds; pairs could overlap as slots became available.

Source hashes passed for all six copies. The 475 copied files were also checked against the original checkout and matched. Agents diagnosed code without modifying it or running application tests.

Copy exclusions included dependencies, Git data, build/cache output, local agent configuration, secret environment files, prior Claude outputs, design-screen assets and the migration dump. These identical exclusions avoid irrelevant configuration, credentials and bulk data entering either side.

The transcript metrics count native Codex model responses and tool calls, including agent status messages. A `functions.exec` or Node call can batch many shell commands or MCP requests, so tool calls are not individual searches or PRISM invocations. Input processed sums per-response `input_tokens`; Codex already includes cached input in this field. Work context is final minus first response input size. Tool output is recorded tool-result characters divided by four, an estimate that includes search output and wrappers, not only source code.

Mean initial context was 29,586 tokens without and 30,020 with. The prompts differed in navigation instructions; their initial sizes are close but not exactly equal. Controller preparation, indexing, measurement and scoring are excluded from agent totals.

The billable column is the plan's comparison proxy: uncached input + 1.25 × cache writes + 0.1 × cache reads. It is not an actual OpenAI invoice or a model-price claim. All observed cache-write counts were zero.

Existing backend-test mentions were checked against actual test modules/classes. This measures naming an existing test, not proving that it covers the behavior; generic PRISM mappings can be weak. Detailed caller coverage in scores.json matches unqualified caller names against the complete indexed direct-caller list; it is indicative and can be ambiguous. PRISM's impact display can truncate callers, so its displayed list was not used as the denominator.

Primary scoring requires the owner name for class methods, avoiding a false match between a legacy detail view's inherited get_object and RestaurantViewSet.get_object. This clarification leaves the earlier CLI scores unchanged. The fixed key penalizes plausible neighboring primaries: APICache.get instead of set (task 11), and resolvePostAuthPath instead of getPostAuthRedirectPath (task 12). These functions can be defensible investigation points. The scores measure agreement with this plan's key rather than confirmed bug fixes. Three repetitions on one repository do not establish a general performance guarantee.

## Previously measured modelled estimate

The existing scripted harness estimates 366,127 tokens without PRISM versus 25,807 with (93.0% reduction). Its best-case baseline is 114,200 (77.4% reduction). This harness is given the target symbols and replays fixed navigation strategies; it does not measure real agent decisions.

## Evidence and reproduction

Raw native transcripts, final answers, current answer-key locations, hashes, metrics and detailed scores are stored under `.benchmark-runs/2026-10-03-codex-mcp/` (ignored local artifacts).

```powershell
python -m tests.benchmarks.agent_prepare --repo D:/Projects/Platforma/Platforma --plan C:/Users/mahaj/Downloads/agent-benchmark-plan.md --output <NEW-DIRECTORY> --transport mcp
# Run fresh Codex subagent pairs with the report-only prompts captured in the archived transcripts.
python -m tests.benchmarks.agent_collect --session-dir C:/Users/mahaj/.codex/sessions/2026/10/03 --parent 01a0fe60-70db-76d3-870d-344f0fc6a32d --output .benchmark-runs/2026-10-03-codex-mcp --agent-prefix mcp_
python -m tests.benchmarks.agent_score .benchmark-runs/2026-10-03-codex-mcp
python -m tests.benchmarks.agent_report .benchmark-runs/2026-10-03-codex-mcp --output docs/agent-benchmark-results-mcp-2026-10-03.md --transport mcp
```

Measurement/scoring regression tests: `python -m pytest tests/test_agent_measure.py`.
