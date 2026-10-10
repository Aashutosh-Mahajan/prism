# Prism benchmark protocol

## 1. Question and scope

Does Prism reduce provider-reported tokens required to complete verified software changes, while preserving correctness, compared with an agent using ordinary targeted discovery? Measure CLI and MCP independently. Measure indexing and knowledge-authoring costs separately, then include them in lifecycle totals.

The baseline must be competent: allow targeted search, file reads, normal code tools and tests. **Never require it to scan the entire repository.** Such a requirement would inflate the baseline and answer the wrong question. A full-scan baseline can be an explicitly labelled diagnostic only.

Existing two-task preflight results (18.4% CLI and 20.5% MCP processed-input savings) are calibration history, not confirmation. Earlier tool-only results included a CLI regression. Use new held-out tasks for the main study; never count those known tasks as independent confirmation.

## 2. Experiments and arms

### Primary: native tool-only editing

| Arm | Agent environment | Delivery |
|---|---|---|
| B | Ordinary shell/search/read/edit/test tools | No Prism data, hooks, schemas, instructions or index access |
| C | Same tools plus Prism CLI | Agent invokes actual CLI; hooks disabled |
| M | Same tools plus native Prism MCP, lean profile | Agent invokes actual MCP; hooks disabled |

Use identical task text and verification requirements. Preserve unavoidable real transport overhead: MCP tool schemas, discovery, tool responses, shell wrappers and additional turns all belong in the result. Do not pad the baseline to hide MCP overhead. Document exact instruction differences. Permit fallback search in treatments and measure it; forcing agents to use insufficient evidence would test an artificial workflow.

### Separate experiments

| Experiment | Arms/design | Question |
|---|---|---|
| Native preflight | B, CLI-backed hook, MCP-backed host adapter if supported | Does real first-turn delivery reduce total usage? |
| Matched packet replay | Same verified packet via matched prompts | How much variance comes from agent behaviour? Diagnostic only |
| Session reuse | Fresh matched sequences of 5 related edits, B/C/M | Does persistent context help across edits and reconnects? |
| Local lifecycle | Cold build, unchanged query, small update, branch switch, rebuild | What local time, storage and refresh work does knowledge cost? |
| Generalisation | Second model and additional repositories | Do effects survive outside the primary configuration? |
| Ablations | One change at a time on a development suite | Which component produces the saving? |

Do not call precomputed packet injection a native hook test. Verify host activation with trace evidence. Unsupported host integrations are reported as unavailable, not silently replaced with replay. CLI and MCP caches must start in equivalent states. Use disjoint development and confirmation tasks for tuning.

## 3. Scale and gates

| Stage | Suggested size | Purpose and gate |
|---|---:|---|
| Local reliability | Matrix in section 8 | Zero unresolved critical integrity failures |
| Harness smoke | 2 tasks × 1 repetition × 3 arms = 6 sessions | Counters, isolation, native transport and scoring verified |
| Calibration | 12 separate tasks × 2 repetitions × 3 arms = 72 sessions | Runtime, variance and sample-size simulation |
| Heavy primary | 3 repositories × 32 tasks × 3 repetitions × 3 arms = 864 sessions | Fixed, preregistered confirmation |
| Preflight extension | 12 held-out tasks × 3 repetitions × 3 arms = 108 sessions | Delivery comparison; own inference family |
| Session extension | 12 sequences × 5 edits × 3 repetitions × 3 arms = 108 sessions, 540 edits | Sequence is the independent cluster |
| Second-model replication | 24 tasks × 3 repetitions × 3 arms = 216 sessions | Model-specific replication |

All stages above total 1,374 agent sessions, with session-extension sessions containing five edits. This is a planning envelope, not a guaranteed adequate sample size or a request to spend it now. Calibration simulations may require more tasks, especially to establish a narrow correctness margin. Budget limits can lead to an inconclusive study; never lower the evidence threshold afterward.

Repositories should span at least three architectures/language mixes and small/medium/large indexed sizes. Prism itself can be a dogfood suite but should not be the sole or dominant external-efficacy evidence. Include supported and imperfectly supported patterns. Record repository selection bias; three repositories cannot establish universal generalisation.

## 4. Task suite and independent oracle

For each repository's 32 primary edit tasks, target:

| Category | Count | Examples |
|---|---:|---|
| Local behaviour fixes | 6 | Boundary, expiration, validation, rounding |
| Multi-file contract changes | 6 | API field, type, constructor and consuming UI |
| Cross-module bugs | 6 | State transition, cache invalidation, data flow |
| Feature additions | 4 | Small capability with existing extension points |
| Refactors preserving behaviour | 4 | Signature migration and all relevant callers |
| Test/config/build changes | 3 | Test discovery, configuration defaults, packaging |
| Ambiguous or unsupported requests | 3 | Correct abstention or justified clarification |

Balance easy/medium/hard tasks and lexical/symptom-only requests. No more than a quarter should be trivial single-location edits. Maintain a separate negative-localisation suite if its scoring cannot use the edit-task binary outcome.

Prefer mined real issues or realistic independently seeded bugs. Two reviewers establish requirements and hidden tests before running agents. Validate that tests fail on the starting bug and pass on at least one valid solution. Include boundary, regression and cross-layer contract tests. Do not require an exact patch: independently valid implementations receive credit. For abstention tasks, define the required response and prohibited edits precisely.

Freeze task prompt, starting source hash, setup commands, hidden tests, acceptance rules and reviewer key. Keep hidden tests, solution patches, reports and benchmark machinery outside agent-visible/indexed directories. Prevent inherited parent conversation, shared memory, other agents' patches or task solutions from leaking. Do not suppress legitimate project guidance except benchmark-contaminating or treatment-specific instructions; record the controlled substitutions.

## 5. Execution and isolation

1. Freeze Prism commit plus dirty-diff hash (prefer a clean release), dependencies, model identifier, reasoning settings, host version, OS, hardware and limits. Do not benchmark an unexplained changing worktree.
2. Prepare dependencies before timed agent execution, equally across arms. Run baseline test health checks. If full builds cannot run, resolve it before confirmation or explicitly narrow the study scope.
3. Make a separate source copy and writable caches per task/repetition/arm. Source trees must match before treatment setup. Use isolated consent/config registries, working directories, sessions and server processes. Do not modify user-wide installations.
4. Measure treatment setup in a separate build ledger. Verify enabled/fresh status, inventory, source hashes and actual MCP connection. Restore equivalent warm snapshots or rebuild according to the registered regime.
5. Generate a seeded shuffled schedule of task/repetition blocks; balance B/C/M order within blocks. Execute blocks close in time. Prefer balanced sequential execution on shared hardware; concurrent runs are allowed only with isolated resources and a recorded contention plan.
6. Start each primary agent with fresh history. Disable unintended Prism hooks in B/C/M. Give equal time/turn/token budgets and identical task/verification prompts. Record all tools and schemas actually exposed.
7. Save every provider response, tool event, usage event, source patch, stdout/stderr, test log and timestamp. Evaluate final patches in isolated evaluator copies using frozen tests.
8. Blind reviewers to arm and shuffle review order. Resolve disagreements with a recorded adjudication. Tests are necessary but do not replace reviewing requirement coverage and unacceptable shortcuts.
9. Do not inspect comparative main-study results to choose early stopping or tune Prism. Any fix starts a separately versioned campaign or is a declared amendment with original results preserved.

## 6. Tokens, cost and boundaries

Primary endpoint: **provider-reported processed input per assigned task**, including cached input once and every attempt. Secondary: generated output, input plus output, uncached input, provider cost, elapsed time and cost per verified success.

Maintain one raw usage row per unique provider response ID. Some providers emit cumulative usage and others per-response deltas: normalise once and verify against raw events. Never sum both cumulative snapshots and deltas. Store the original schema and parser version. Cached input is usually a subset of input, not an extra amount; verify provider semantics rather than assuming it. Record output/reasoning subsets without double counting.

Report these separately:

- Total processed input, cache-read input, uncached input, cache-write input where separately priced, output and any separately billed category.
- Actual currency cost only with dated provider prices and verified accounting semantics. If unavailable, report a clearly labelled proxy and a cache-weight sensitivity sweep; never call the proxy dollars.
- Model turns, retrieval calls, fallback searches, reread source volume, duplicate packet delivery, tool-output bytes and tokenizer counts. `characters/4` is only an estimate.
- First-turn overhead and available component estimates; total input remains inclusive. Hidden provider overhead that cannot be attributed is marked unknown.
- Maximum observed request input/context occupancy, distinct source exposure and cumulative processed input as different quantities.
- Agent time, evaluator time, setup time, narrative-authoring model tokens, refresh time, disk and peak memory. Measure warm/cold Prism state separately from provider prompt caching.

Index construction can consume zero model tokens while costing CPU/time. If an agent writes narratives, decisions or summaries, count those model calls as knowledge-building tokens. Include all preflight model calls. Keep human development and benchmark orchestration separate from product lifecycle totals, with explicit boundaries; retain an overall experiment-spend ledger as well.

For metric X and N edits:

`Prism lifecycle X(N) = initial build X + knowledge authoring X + refresh X(N) + sum(edit X)`

Compare against baseline setup plus baseline edits. Report N = 1, 5, 10, 25, 50, 100 using measured workloads or clearly labelled projections. Under a constant per-edit assumption only, break-even is the smallest integer N satisfying `setup_delta + N * per_edit_delta <= 0`. If per-edit delta is nonnegative and setup is positive, there is no break-even. If setup is zero and edits save tokens, the first edit already saves tokens. Compute tokens, money and time separately.

## 7. Correctness, failures and scoring

Primary correctness outcome is binary verified success: all mandatory requirements, hidden tests and required regressions pass, with no prohibited shortcut. Report weighted diagnostic scores separately: requirements 40, hidden behaviour tests 30, regressions 20, patch review 10. Freeze task-specific rubrics; a high diagnostic score cannot convert a failed task into success.

Keep every assigned trial in the outcome ledger. Tool crashes, inability to find code, timeouts, incomplete edits and test failures remain failures with consumed tokens. A low-token failure is not an efficiency win.

Predeclare one optional recovery attempt for infrastructure failures, identical across arms. Retain the failed attempt and add all attempt usage/time to its assigned trial. Record first-attempt success and eventual success separately. Do not retry ordinary wrong answers unless recovery is itself part of the registered workflow for every arm. A failure before any model turn may be rescheduled, but retain its record and setup cost.

Missing telemetry is not zero. Reconcile provider logs; if unrecoverable, report missingness and bounded sensitivity results. Do not silently drop incomplete pairs or declare the primary efficiency claim supported without defensible accounting. Zero-input prelaunch failures remain in correctness and spend totals; do not add arbitrary constants to make log ratios work.

## 8. Reliability and transport matrix

Run deterministic checks on small synthetic repositories with independently known expected facts. These gates validate product behaviour and do not establish agent token savings.

| Area | Cases | Required evidence |
|---|---|---|
| Indexing | Supported languages, syntax errors, ignores, generated/vendor files, Unicode, large files | Expected inventory; parse failures explicit; exclusions honoured |
| Freshness | Edit/add/delete/rename, branch switch, preserved mtime edits, worktree move | No stale source represented as current; correct invalidation |
| Session memory | Same/new session, reconnect, cross CLI/MCP, repeat request, truncated packet | Only actually delivered unchanged source can become references |
| Retrieval | Scalars, producers/types, literals, callers, tests, ambiguous symbols | Frozen relevance/coverage key; incomplete lists labelled |
| Budgeting | Low/default/high budget, long symbol, no match | Bounds follow documented estimate; actual tokenizer size recorded |
| Cache | Cold/warm, eviction, corrupt/truncated cache, config change, concurrent writers | Equivalent valid answers; safe recoverable failures; no leaked state |
| MCP | Native initialize/list/call, lean/full, compact/JSON, malformed args, restart | Protocol compliance, expected errors, no double-rendered packet |
| CLI | Exit codes, stderr/stdout, paths with spaces, Unicode, piping | Machine-readable output intact; errors actionable |
| Parity | Identical snapshot/query/budget/mode/session history | Semantic evidence equality; strip only documented transport metadata |
| Hooks | Actual activation, cold start, timeout, unavailable server, edit refresh | Trace proves invocation/delivery; no duplicate context injection |
| Consent | Disabled/paused/uninitialised, inaccessible registry | Correct gating; no unauthorised setup or writes |
| Isolation | Two repos/sessions in parallel, symlinks and excluded paths | No cross-repository evidence or excluded-source disclosure |
| Robustness | Interrupted write, locked database, permission denied, missing dependency | Bounded failure/recovery; existing artifacts not corrupted |
| Optional features | Semantic on/off, model unavailable, graph hints absent/stale | Offline fallback documented; feature costs counted |

Critical gate failures: wrong-repository source, unlabelled stale source, omitted unseen source due to session memory, corrupted source, or falsely complete literal coverage. Stop confirmation until resolved; preserve failed gate results.

For performance, measure at least 30 repeated local queries per size/state after a declared warm-up, reporting median/p95 and environment. Register SLOs after calibration and before confirmation; do not invent universal latency limits. Profile large-repository memory and changed-file refresh scaling separately.

## 9. Analysis and decision rules

Tasks are independent clusters; repetitions are repeated observations. For session experiments, the whole sequence is the cluster. Never treat turns or individual assertions as independent samples.

Primary efficiency estimand: equal-repository-weighted ratio of mean per-assigned-task processed input, including failures and retries. Within each repository, average repetitions per task, then tasks; combine repository means equally. Report pooled total-spend ratio too, labelled workload-weighted. Report paired task distributions and task wins, median and tail regressions; do not report only the best tasks.

Use a paired task-cluster bootstrap, stratified within repository, retaining each task's complete repetition and arm vectors. Use at least 10,000 seeded draws. This estimates uncertainty conditional on the chosen repositories. Report each repository separately. Broader repository-population claims need more repositories and a justified hierarchical analysis; resampling three repositories alone is weak evidence.

Two planned comparisons: C/B and M/B. Use conservative 97.5% two-sided intervals for each comparison's efficiency ratio and correctness difference to control the two-comparison family. Both efficiency and correctness must pass within a comparison; no cherry-picking an endpoint. Apply Holm adjustment to inferential secondary comparisons; label unplanned slices exploratory.

Default preregistered targets, adjustable only before main data:

- Useful token saving: efficiency interval upper bound <= 0.80 (at least 20% reduction supported).
- Large saving: upper bound <= 0.50 (at least 50% reduction supported).
- Very large saving: upper bound <= 0.30 (at least 70% reduction supported).
- Correctness non-inferiority: lower bound of treatment-minus-baseline verified-success difference > -0.05.
- Operational guardrail: register an acceptable latency ratio and zero critical integrity failures.

If the interval upper bound is below 1 but above 0.80, report evidence of some savings without claiming the useful-effect target. If it spans 1, report inconclusive. If its lower bound is above 1, report evidence of higher token usage. If correctness non-inferiority is not established, token improvements are a trade-off or inconclusive, not a successful release claim. Declare both transports successful only if each passes independently.

Use calibration distributions to simulate power for the ratio and correctness margin under task clustering. Target 80–90% power and record assumptions. Repetitions do not substitute for diverse tasks. If the heavy sample cannot establish a five-percentage-point margin, increase it or report uncertainty.

Sensitivity analyses: task category/difficulty/repository, all-assigned versus successful-only (secondary, selection-biased), cold versus warm state, retry contribution, cache pricing weights, missing telemetry bounds and high-cost outliers retained versus clearly labelled robust summaries.

## 10. Ablations and optimisation feedback

Use a held-out development suite to compare packet budgets (600/1200/2000/4000), lean/full MCP schemas, compact/structured rendering, session reuse on/off, preflight on/off, optional semantic retrieval on/off and narratives on/off. One factor at a time first; use a planned factorial design only with adequate budget. Select settings on development tasks, then freeze them for confirmation.

Trace every expensive trial: discovery turns, duplicate source reads, oversized packets, redundant tool calls, missing caller/type/test evidence, irrelevant retrieval and dependency probes. Optimise the largest measured contributor. Large percentage claims must come from the confirmation study after changes, not extrapolated packet-size improvements.

## 11. Evidence bundle and release checklist

Keep: registration, source/config/prompt hashes, schedule, environment manifest, raw transcripts, normalised response usage, attempts ledger, build ledger, patches, test outputs, blind scores, adjudications, deviations, analysis source/version and report. Store credentials separately; publish redacted traces with stable hashes and accounting intact.

Required charts: per-task paired token ratios with parity line; CLI/MCP intervals; success rates and difference intervals; processed input/cache/output components; lifecycle cost versus edit count; latency versus correctness; failure and fallback counts. Show sample sizes and exclusions on every applicable chart. Do not mix proxy tokens with actual tokens on one unlabeled scale.

Final gate: independent re-computation of totals from raw events, no missing assigned trials, paired source hashes verified, hidden tests reviewed, all attempts counted, both transports reported, lifecycle boundaries stated and conclusions limited to tested configurations.
