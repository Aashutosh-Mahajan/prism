# Codex agent benchmark — 2026-10-03

Six fresh Codex subagents completed 12 reports each, in three paired runs. All used `gpt-6.1-sol` with `medium` reasoning effort.

PRISM changed average tool output by **-34.8%**, total input processed by **-1.5%**, and completion time by **+42.3%**. Mean primary-function scores were **9.67/12 with PRISM** and **9.00/12 without**.

These are measured agent runs. The separate modelled estimate below is not a substitute for them.

## Measured results

| Run | Agent | Model turns | Tool calls | Input processed | Billable proxy | Work context | Tool output estimate | Seconds | Correct /12 | Partial | Tasks naming backend tests |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | without | 9 | 8 | 507,036 | 106,140 | 52,274 | 47,092 | 180.1 | 9 | 3 | 8 |
| 1 | with | 16 | 15 | 718,872 | 107,621 | 34,927 | 31,404 | 281.7 | 10 | 2 | 6 |
| 2 | without | 10 | 9 | 650,017 | 123,438 | 61,600 | 55,377 | 191.7 | 9 | 3 | 9 |
| 2 | with | 10 | 9 | 488,281 | 86,579 | 38,578 | 35,721 | 301.9 | 10 | 2 | 9 |
| 3 | without | 10 | 9 | 603,213 | 113,152 | 55,209 | 51,974 | 191.7 | 9 | 3 | 9 |
| 3 | with | 11 | 10 | 526,064 | 88,304 | 36,108 | 33,556 | 218.1 | 9 | 3 | 7 |
| **Mean** | **without** | 9.7 | 8.7 | 586,755.3 | 114,243.3 | 56,361.0 | 51,481.0 | 187.8 | 9.0 | 3.0 | 8.7 |
| **Mean** | **with** | 12.3 | 11.3 | 577,739.0 | 94,168.0 | 36,537.7 | 33,560.3 | 267.2 | 9.7 | 2.3 | 7.3 |

## Per-task scoring

C = correct primary; P = expected function appears as a dependent; W = neither. The supplied alternatives for tasks 5, 6 and 8 were retained. No alternatives were added after seeing results.

| Task | Run 1 without | Run 1 with | Run 2 without | Run 2 with | Run 3 without | Run 3 with |
|---|---|---|---|---|---|---|
| 1 | C | C | C | C | C | C |
| 2 | C | C | C | C | C | C |
| 3 | C | C | C | C | C | C |
| 4 | C | C | C | C | C | P |
| 5 | C | C | C | C | C | C |
| 6 | C | C | C | C | C | C |
| 7 | C | C | C | C | C | C |
| 8 | C | C | C | C | C | C |
| 9 | P | C | P | C | P | C |
| 10 | C | C | C | C | C | C |
| 11 | P | P | P | P | P | P |
| 12 | P | P | P | P | P | P |

## Direct caller mentions

Across the 12 target functions, the current index lists 76 direct callers. Counts below use textual name matching; full per-task caller lists and matches are retained in scores.json.

| Run | Without PRISM | With PRISM |
|---|---:|---:|
| 1 | 11 / 76 | 36 / 76 |
| 2 | 17 / 76 | 44 / 76 |
| 3 | 22 / 76 | 36 / 76 |
| **Mean** | 16.7 / 76 | 38.7 / 76 |

## Protocol and interpretation

Platforma currently indexes 351 files and 60,200 lines. Each repetition used two identical fresh source copies; only the PRISM side was indexed. The consent registry was isolated per repetition. Agents received bug reports, not target names or the answer key, and had fresh histories. Both sides of each pair ran concurrently. Pair starts were dispatched sequentially within seconds; pairs could overlap as slots became available.

Source hashes passed for all six copies. The 475 copied files were also checked against the original checkout and matched. Agents diagnosed code without modifying it or running application tests.

Copy exclusions included dependencies, Git data, build/cache output, local agent configuration, secret environment files, prior Claude outputs, design-screen assets and the migration dump. These identical exclusions avoid irrelevant configuration, credentials and bulk data entering either side.

The transcript metrics count native Codex model responses and tool calls. A `functions.exec` call can batch many shell commands, so tool calls are not individual searches or PRISM invocations. Input processed sums per-response `input_tokens`; Codex already includes cached input in this field. Work context is final minus first response input size. Tool output is recorded tool-result characters divided by four, an estimate that includes search output and wrappers, not only source code.

Mean initial context was 29,662 tokens without and 29,766 with. The prompts differed in navigation instructions; their initial sizes are close but not exactly equal. Controller preparation, indexing, measurement and scoring are excluded from agent totals.

The billable column is the plan's comparison proxy: uncached input + 1.25 × cache writes + 0.1 × cache reads. It is not an actual OpenAI invoice or a model-price claim. All observed cache-write counts were zero.

Existing backend-test mentions were checked against actual test modules/classes. This measures naming an existing test, not proving that it covers the behavior; generic PRISM mappings can be weak. Detailed caller coverage in scores.json matches unqualified caller names against the complete indexed direct-caller list; it is indicative and can be ambiguous. PRISM's impact display can truncate callers, so its displayed list was not used as the denominator.

The fixed key penalizes plausible neighboring primaries: APICache.get instead of set (task 11), and resolvePostAuthPath instead of getPostAuthRedirectPath (task 12). These functions can be defensible investigation points. The scores measure agreement with this plan's key rather than confirmed bug fixes. Three repetitions on one repository do not establish a general performance guarantee.

## Separate modelled benchmark

The existing scripted harness estimates 366,127 tokens without PRISM versus 25,807 with (93.0% reduction). Its best-case baseline is 114,200 (77.4% reduction). This harness is given the target symbols and replays fixed navigation strategies; it does not measure real agent decisions.

## Evidence and reproduction

Raw native transcripts, final answers, current answer-key locations, hashes, metrics and detailed scores are stored under `.benchmark-runs/2026-10-03-codex/` (ignored local artifacts).

```powershell
python -m tests.benchmarks.agent_prepare --repo D:/Projects/Platforma/Platforma --plan C:/Users/mahaj/Downloads/agent-benchmark-plan.md --output <NEW-DIRECTORY>
# Run fresh Codex subagent pairs with the report-only prompts captured in the archived transcripts.
python -m tests.benchmarks.agent_collect --session-dir C:/Users/mahaj/.codex/sessions/2026/10/03 --parent 01a0fe60-70db-76d3-870d-344f0fc6a32d --output .benchmark-runs/2026-10-03-codex
python -m tests.benchmarks.agent_score .benchmark-runs/2026-10-03-codex
python -m tests.benchmarks.agent_report .benchmark-runs/2026-10-03-codex --output docs/agent-benchmark-results-2026-10-03.md
```

Measurement/scoring regression tests: `python -m pytest tests/test_agent_measure.py` (4 passed).
