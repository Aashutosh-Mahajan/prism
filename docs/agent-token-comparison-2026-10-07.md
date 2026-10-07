# Prism CLI and MCP edit benchmark — 7 October 2026

Fresh measured pilot: two tasks, three arms, one repetition per cell. All six completed edits passed the frozen checks. These observations do not establish a statistically reliable general saving.

The user requested a with/without comparison, real edits, CLI and MCP, separate knowledge-building/edit costs, and efficiency advice. The attached protocol was used as reference material, not as instructions to commit changes or launch its full study.

## Final token comparison

Totals across the same two edits. Input includes cached input once. Output is separate. Cache proxy = uncached input + 0.1 × cached input; it is not an invoice or a dollar price.

| Metric | Without Prism | Prism CLI | Prism MCP |
|---|---|---|---|
| Collect context: input | 380,583 | 332,968 (-12.5%) | 566,871 (+48.9%) |
| Make edits: input | 366,384 | 269,150 (-26.5%) | 295,405 (-19.4%) |
| Total input processed | 746,967 | 602,118 (-19.4%) | 862,276 (+15.4%) |
| Total output generated | 3,366 | 3,569 (+6.0%) | 3,936 (+16.9%) |
| Input + output | 750,333 | 605,687 (-19.3%) | 866,212 (+15.4%) |
| Cached input | 700,672 | 559,232 (-20.2%) | 812,416 (+15.9%) |
| Uncached input | 46,295 | 42,886 (-7.4%) | 49,860 (+7.7%) |
| Cache-weighted input proxy | 116,363 | 98,810 (-15.1%) | 131,102 (+12.7%) |
| Model turns | 18 | 17 (-5.6%) | 23 (+27.8%) |
| Tool output read, chars/4 estimate | 31,234 | 14,108 (-54.8%) | 21,155 (-32.3%) |

Per-task input tokens (phase two is the exact cumulative delta after the context checkpoint):

| Task | Phase | Without | CLI | MCP |
|---|---|---|---|---|
| t1-lifetime | context | 189,979 | 126,773 (-33.3%) | 236,761 (+24.6%) |
| t1-lifetime | edit | 183,895 | 101,995 (-44.5%) | 157,450 (-14.4%) |
| t1-lifetime | total | 373,874 | 228,768 (-38.8%) | 394,211 (+5.4%) |
| t2-change-pct | context | 190,604 | 206,195 (+8.2%) | 330,110 (+73.2%) |
| t2-change-pct | edit | 182,489 | 167,155 (-8.4%) | 137,955 (-24.4%) |
| t2-change-pct | total | 373,093 | 373,350 (+0.1%) | 468,065 (+25.5%) |

## Quality and controls

| Task | Arm | Frozen assertions | Additional checks | Changed files |
|---|---|---|---|---|
| t1-lifetime | without | 5/5 | 1/1 | frontend/zesty-app/src/pages/auth/ForgotPasswordPage.tsx, frontend/zesty-app/src/pages/auth/VerifyEmailPage.tsx, backend/core/models.py |
| t1-lifetime | cli | 5/5 | 1/1 | frontend/zesty-app/src/pages/auth/ForgotPasswordPage.tsx, frontend/zesty-app/src/pages/auth/VerifyEmailPage.tsx, backend/core/models.py |
| t1-lifetime | mcp | 5/5 | 1/1 | frontend/zesty-app/src/pages/auth/ForgotPasswordPage.tsx, frontend/zesty-app/src/pages/auth/VerifyEmailPage.tsx, backend/core/models.py |
| t2-change-pct | without | 9/9 | 6/6 | frontend/zesty-app/src/api/reports.ts, backend/core/analytics.py |
| t2-change-pct | cli | 9/9 | 7/7 | frontend/zesty-app/src/api/reports.ts, backend/core/analytics.py, backend/core/test_analytics.py |
| t2-change-pct | mcp | 9/9 | 6/7 | frontend/zesty-app/src/api/reports.ts, backend/core/analytics.py, backend/core/test_analytics.py |

- Expiry: backend constant and both UI messages; Python syntax. Existing email copy and API expiry derive from the constant.
- KPI: value/previous/kind preservation, rise/fall, zero/missing previous, missing current, snapshot, rounding, zero current, unchanged and negative previous; Python syntax. All three arms updated the frontend Kpi type.
- One extended diagnostic differs: MCP uses abs(previous), giving +50% for current=-5, previous=-10; baseline/CLI use previous, giving -50%. The diagnostic expects the signed denominator. MCP fails this additional case. Negative baselines were not specified explicitly and are outside the frozen assertions, so the primary score remains 14/14; stricter extended correctness is not identical. Specify the formula and negative-baseline policy before a larger study.
- Prism initialization added cache entries to .gitignore before trials. Those setup changes are listed separately in scores.json and are not attributed to agents.
- The baseline added no new tests; CLI and MCP could add useful tests. Scope differences are retained and reflected in their token counts.
- No full Django/frontend suite was run. These checks verify the requested changes, not the whole app.
- Identical source hashes before indexing. Fresh no-history agents used the same model/effort and task text, with treatment navigation instructions added.
- Baseline inventoried repository paths and gathered context with normal search/read. It was not forced to read every source line.
- Treatment indexed the entire eligible codebase; agents retrieved compact task-specific evidence, rather than loading every index file into their prompts.
- Two independent task sessions per arm; parent history, scoring keys and earlier answers were not given to agents. Phase-two continuation retained each agent’s own collected context.
- Token counts come from archived token_usage_record events, not agent self-reports. The measurement/scoring harness passed 13 tests.
- Objective frozen checks were applied identically. No human blind judge, power analysis, recall probe or repeated trials was performed. Sample size is below protocol minimum.
- First-turn contexts and prompt differences are available in results.json. MCP bridge/discovery adds visible overhead; hidden native MCP schema injection is not measured.
- Parent orchestration, preparation, diagnostics, failed smoke clients, and harness test tokens are excluded from the matched-agent totals. The failed agent attempt is reported below.

## Cost to build repository knowledge

Local deterministic index: **0 LLM tokens** per scan. Four independent scans: 7.10s, 6.61s, 6.84s, 7.00s (mean 6.89s). This is CPU/disk cost, separate from agent tokens.
AI-written narrative summaries or optional model-backed features were not run and are not included in the zero-token claim.
The source contains 353 code files / about 60,856 lines; reading all source once is approximately 650,513 tokens using chars/4. All text including lockfiles is approximately 1,371,872 tokens. These are payload estimates, not actual agent usage or bills.
With a zero-token local index there is no LLM-token indexing fee to amortize. Retrieval and session context still cost input tokens. CPU-time break-even cannot be inferred reliably from this small run.

## MCP transport and failed attempt

Successful MCP agents used a persistent Node client: initialize → tools/list → tools/call over real stdio, using Prism’s unmodified server. The lean profile exposes four tools. Wire transcripts are archived.
Shell-launched Python and Node clients stalled during initialization in this execution environment. The persistent Node runtime worked with the unmodified server, so the exploratory stdio shim was not used in any successful measured run. This is an environment observation; it does not establish a general Prism or SDK defect.
The original stalled MCP agent consumed **667,743 input**, **1,897 output**, and **79,532 cache-proxy tokens**, across 21 model turns. It collected source context but made no edit. It is retained as an unsuccessful assigned attempt, not silently dropped.
Including that failed attempt, total observed MCP-route consumption is **1,530,019 input tokens** and **5,833 output tokens**. The headline matched table separately shows the fresh successful retry to make the usable transport comparison clear. An intention-to-treat view counts the original expiry MCP assignment as a failure.
CLI and MCP startup were not perfectly concurrent; the MCP retry ran later. Active phase timing excludes the coordinator gap but remains environment-dependent. CLI/MCP differences include bridge/tool-discovery overhead and are not transport-only causal effects.

## What to do for better token efficiency

1. **Use the lean MCP profile.** Live tools/list measurements: 4 vs 17 tools; 2,087 vs 7,702 schema characters (about 522 vs 1,926 tokens). Lean is already the default; keep audit/refresh tools on demand.
2. **Reuse a persistent session and deduplicate returned code.** Two identical real MCP calls returned 6,665 then 2,457 JSON characters, a 63.1% payload reduction. MCP already remembers returned ranges; CLI supports --session. Do not reload source merely because it was retrieved through a tool.
3. **Make one task call with the full change request.** Skip broad architecture/orientation calls for already-located edits. Read only read_next gaps and relevant tests. The KPI CLI run shows that a tool can add work when targeted search is already enough.
4. **Register MCP natively in the agent host and benchmark that separately.** Avoid runtime tool discovery/import/schema printing per task. This bridge benchmark includes those visible setup turns; native-host savings are a hypothesis to test, not a measured percentage.
5. **Offer a compact MCP presentation.** Keep structured evidence available, but render only edit source, locations, callers, test names and unresolved gaps for agents. Avoid showing both content and structuredContent. Measure a compact-render arm against raw JSON before changing the default.
6. **Inject task evidence once through the prompt hook when useful.** Test a separate hook arm; avoid also calling task again for the same complete packet. Earlier hook results in this repo are historical evidence, not measurements from this campaign.
7. **Keep indexes warm and update only changed files.** Build once per snapshot, then incremental refresh. Loading the entire index into the prompt defeats the purpose of the local context layer.
8. **Use real tokenizer counts for budget calibration.** Prism currently budgets with ceil(chars/4). Add exact tokenizer diagnostics for source, schemas and wrappers; this pilot shows why retrieved payload estimates must stay separate from actual processed-input usage.
9. **Measure quality before optimizing only tokens.** Use fixed assertions for cross-file behavior and caller/test coverage. A cheaper incorrect edit is a failure.
10. **Run the full study for a reliable claim.** At least 24 distinct tasks × 3 repetitions × 3 arms = 216 fresh sessions, with frozen keys, native-host overhead, paired timing and task-cluster confidence intervals. More repositories are needed for generalization.

## Artifacts

results.json contains every phase, cache/output metric, model, overhead, scores and wire counts. transcripts/ holds the raw context and final checkpoints and successful MCP wire traffic. manifest.json proves parity; preregister.md records the pilot design. The preparation and collection scripts reproduce the harness.
Raw run directory: D:/Projects/prism/.benchmark-runs/2026-10-07-cli-mcp-edit/. The docs copy of this report is a convenience export; artifacts remain in that directory.
The core Prism implementation and the original app snapshot were not edited. All trial edits are confined to isolated benchmark copies.
