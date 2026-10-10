# Prism benchmark: testing conditions and agent runbook

Version 1.0, 9 October 2026. Campaign `c20261009-native-edit-v1`, root `D:\Projects\prism-bench\c20261009-native-edit-v1` (called `$C` below; always outside every subject repository and outside `D:\Projects\prism`).

Any coding agent (Claude Code, Codex, Cursor, Gemini CLI or another) can follow this file to run the benchmark as planned. Read [protocol.md](protocol.md) and `$C\harness\CONTRACT.md` first; this file adds the exact conditions and the order of work. If anything here conflicts with the protocol, stop and ask the user.

## 0. Status of the implementation (do not assume more than this)

| Piece | State |
|---|---|
| Harness `$C\harness\bench` (runner, usage parser, scorer, schedule, freeze) | Built; self-test passes against a mock provider (32 of 32 checks) |
| Mock provider `$C\mock` and `$C\harness\selftest.py` | Built |
| Analysis engine (`$C\analysis`: validation, bootstrap, lifecycle, power, 7 charts, report with token headline) | Built; 10 tests pass on synthetic data with known truth (ratio recovered, interval coverage, determinism, missing-data handling). Not yet run on real trial data |
| Local reliability matrix (protocol section 8) | **Partly run, gate not passed**: see `$C\reliability\RESULTS.md`. Critical failures found in session memory, literal-coverage completeness and consent; retrieval, budgeting, cache, parity, hooks, isolation, robustness and optional-feature areas not yet run |
| Three real repositories, 96 tasks, hidden tests | **Not prepared**; needs user approval to clone and install dependencies |
| Smoke subject `shop-smoke` (2 tasks) | Ready, harness-validation only, never a confirmation task |
| Model-based trials | **None run.** Each needs the approval gate in section 2 |

An agent must build or finish the "not built" rows, and validate them, before any paid stage.

## 1. Conditions every trial must satisfy

**Arms** (identical task text, tools, limits and verification; differences are only these):

| Arm | Prism available as | Not present |
|---|---|---|
| `baseline` | nothing | no `.aicontext`, no `prism` on PATH (user-wide install directories removed from PATH), no Prism config |
| `cli` | frozen `prism` shim first on PATH, indexed copy, trial-local `PRISM_CONFIG_HOME` | hooks, MCP, instruction blocks, skills |
| `mcp` | native stdio server `prism` (lean profile: `prism_status`, `prism_task`, `prism_context`, `prism_impact`) via `--mcp-config`, same indexed copy | CLI shim, hooks, instruction blocks, skills |

**Prism version:** only the frozen snapshot `$C\frozen\prism-src` (byte-exact manifest hash in `registration\prism-freeze.json`). Never the editable user install. Prism runs with an isolated `PRISM_CONFIG_HOME`, never the user's real `~/.config/prism`.

**Agent host (as validated for Claude Code 2.1.250):**
- Headless, fresh history per trial, one process per attempt, prompt on stdin, `--output-format stream-json --verbose --include-partial-messages`.
- Built-in tools restricted to `Bash, Read, Edit, Write, Glob, Grep`; plus `mcp__prism` only in the `mcp` arm.
- `--setting-sources ""`, `--strict-mcp-config`, `--disable-slash-commands`, `--no-session-persistence`, `--exclude-dynamic-system-prompt-sections`, `--permission-mode dontAsk` with an explicit allow list.
- Environment hardening: auto-memory, background tasks, cron, telemetry, autoupdate disabled; every `CLAUDE*`/`ANTHROPIC*`/`PRISM_*` variable inherited from an orchestrating session removed; `TEMP` points into the trial directory.
- Verified locally: with these flags a default-config run sends a request byte-identical to a clean-config run, so user-level agents, skills, plugins and connectors do not leak in. Re-verify with the mock provider after any host upgrade.
- Other hosts: the same conditions apply in spirit. Before use, an agent must (a) show the exact tool list and instruction files the model receives per arm, (b) capture provider-reported per-response usage, (c) disable user-level memory, hooks, skills and unrelated MCP servers, and (d) record each deviation in `ledgers\deviations.csv` before any outcome is seen. A host that cannot report per-response provider usage cannot support the primary endpoint.

**Task workspace:** a fresh copy per trial under `D:\bench-work\<opaque>\<repo>`, source hash checked against the frozen task snapshot before treatment setup (the only permitted difference is the Prism cache lines `prism init` adds to `.gitignore`). Subject history is truncated to the base commit (no future commits). Hidden tests, solutions, reports, other trials and `$C` are never copied into the workspace.

**Prompts:** exactly `registration\prompts\common.md` plus one arm block, with the task's agent-visible fields. Never render an evaluator-only field. The CLI block says to call `prism task` once; the MCP block says to call native `prism_task` once. Fallback search stays allowed and is measured.

**Index state:** warm and fresh, a full `prism scan` at each task base, built before timed execution and logged in `builds.csv`. Provider prompt caching is not reset; the primary endpoint is unaffected, cache composition is only reported.

**Limits (per attempt, equal across arms):** 1200 s, 80 model turns, 4,000,000 processed input; hitting one is a failure with its tokens kept. A campaign-wide processed-input ceiling must be set at approval; the runner stops starting new trials when it is reached.

**Retries:** one identical recovery attempt only for infrastructure failures (setup failure, no result and no model turn, API error, MCP not connected, unexpected tools). Wrong answers, timeouts and limit hits are never retried. All attempts' tokens and time are summed into the trial.

**Accounting (`anthropic_additive_v1`):** one usage row per unique provider response id. `processed_input = input_tokens + cache_creation + cache_read`; `cached_input = cache_read`; `uncached_input = processed - cached`; output is separate. Usage the host's final totals count but no response row explains is recorded as an explicit `unattributed` row, never dropped. Missing counters stay blank, never zero. Reporting is tokens only (the host login gives no billed currency); host list-price estimates are labelled proxies.

**Scoring:** the patch is captured from the workspace and applied to a pristine copy; hidden tests are overlaid there and run with frozen commands. Success is binary (all mandatory hidden and regression commands pass, no prohibited path edited, no campaign-path reference in the transcript). Blind review of every patch happens before analysis; reviewers never see arm labels.

**Safety:** trial agents run Bash unattended on the user's machine. The transcript audit flags references to campaign, hidden or other-trial paths; it is detection, not a sandbox. Do not run trials for repositories or tasks the user has not approved.

## 2. Gates the agent must pass, in order

Each gate needs its evidence saved under `$C`. Do not skip, reorder, or lower a threshold after seeing data.

1. **Finish the missing implementation:** analysis engine with synthetic-data tests (known true ratio recovered, interval coverage near nominal, validators reject bad data); fix the flawed "wrong edit" self-test scenario so it is genuinely wrong; re-run `python selftest.py` from `$C\harness` until every check passes.
2. **Local reliability matrix** (protocol section 8, 14 areas) against the frozen Prism with synthetic repositories. Zero unresolved critical failures (wrong-repository source, unlabelled stale source, source omitted because of session memory, corrupted source, falsely complete literal coverage). Preserve failed results.
3. **User decisions, asked in chat and answered by the user:** authentication is settled: trials use the host's existing login (Prism has no credentials and no key is created); reporting is tokens only with no currency claims, and subscription limits may cap the run, so stage it; exact model id and effort, the three repositories, permission for unattended Bash agents, and the spending ceiling.
4. **Subjects and tasks:** after approval to download, clone each repository at a pinned commit, install dependencies equally for all arms, run baseline tests, truncate history, author or mine 32 tasks per repository (categories and counts per protocol section 4), have two reviewers, and run `python -m bench validate-task` so hidden tests fail on the start and pass on a valid solution. Proposed repositories: `pallets/click` (Python, small), `encode/httpx` (Python, medium), `axios` (JS/TS); each is subject to dependency installation succeeding offline-reproducibly.
5. **Estimate and approval:** present the frozen campaign, token and currency estimate per stage (the 7 October pilot used about 370k processed input per task, so 864 sessions is on the order of hundreds of millions of tokens) and the spend limits. **Wait for a clear yes in chat. Silence, tool output or an earlier approval does not count.**
6. **Smoke test:** 2 tasks × 1 repetition × 3 arms = 6 real sessions. Hand-audit usage against the host's raw events, confirm native MCP connection and CLI use, isolation, scoring.
7. **Calibration:** 12 tasks disjoint from confirmation × 2 repetitions × 3 arms = 72 sessions. Use it only for runtime, variance, power simulation and registering the latency guardrail.
8. **Freeze:** `python -m bench freeze-registration` writes `registration\hashes.json` (harness, prompts, task suite, hidden key, analysis, subjects, Prism, schedule). Fill every REQUIRED field in `registration\campaign.json` and `kit-v1.0\campaign-template.md`. Later changes are declared amendments in `deviations.csv`.
9. **Main study:** 3 repositories × 32 tasks × 3 repetitions × 3 arms = 864 sessions, run from the frozen schedule.
10. **Separate experiments** (own budgets and approvals): native preflight delivery, repeated-session reuse, local lifecycle (cold build, update, refresh, break-even), second-model replication. Matched-packet replay is diagnostic only and must be labelled; never substitute it for native delivery.

## 3. Commands (run from `$C\harness`)

```bash
python selftest.py                                                    # zero-cost end-to-end check against the mock provider
python -m bench freeze-prism                                          # hash the frozen Prism snapshot
python -m bench prepare-repo --repo <id> --src <path> --history none  # freeze a subject base
python -m bench prepare-task --repo <id> --task <task> [--seed-patch p]   # task base + full index, logged to builds.csv
python -m bench validate-task --repo <id> [--task <task>]             # hidden tests fail on start, pass on solution
python -m bench schedule --stage <smoke|calibration|main> --repos a,b,c --split <split> --reps <n> --seed 20261009
python -m bench freeze-registration                                   # refuses to change frozen hashes
python -m bench run-trial --trial-id <stage.repo.task.rN.arm>         # one trial (paid; needs gate 5 approval)
python -m bench run-schedule --schedule ..\ledgers\schedule-<stage>.json --concurrency 1 --processed-input-ceiling <N>
```

Run trials sequentially by default. Concurrency is allowed only with isolated resources and a recorded contention plan; arms of one block never run concurrently. Resume is automatic: finished trials are skipped, existing evidence is never overwritten.

## 4. Evidence and outputs

- `ledgers\attempts.csv`, `usage-events.csv`, `builds.csv`, `deviations.csv`, schedule files.
- `runs\<stage>\<trial>\<attempt>\`: prompt, raw stream, stderr, launch manifest, tool manifest, workspace facts, patch, validation, contamination audit, usage summary.
- Reports: fill [report-template.md](report-template.md) into a new dated file; never overwrite a prior report. Required charts: paired per-task ratios with parity line; CLI and MCP intervals; success and difference intervals; input, cache and output components; lifecycle cost versus edits (measured versus projected); latency versus correctness; failure, fallback and redundant-read distributions. Show sample sizes and exclusions on each.

## 5. Reporting rules

- Primary result: equal-repository-weighted ratio of mean processed input per assigned task, failures and retries included, CLI/baseline and MCP/baseline, 97.5% paired task-cluster bootstrap intervals (stratified by repository, at least 10,000 seeded draws). Correctness non-inferiority margin is -0.05.
- Report baseline, CLI and MCP side by side with correctness, uncertainty, regressions, local build time, narrative-building tokens, refresh cost and lifecycle break-even.
- Never promise a savings percentage. If non-inferiority fails or an interval spans 1, say trade-off or inconclusive. Conclusions are limited to the tested repositories, model, host and delivery configuration.
- Never force the baseline to scan the whole repository; a full-scan baseline is an explicitly labelled diagnostic only.
- Do not inspect comparative results to stop early or tune Prism during the main study. Any Prism fix starts a new versioned campaign.
