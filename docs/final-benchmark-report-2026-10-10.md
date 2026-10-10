# Final benchmark report — Prism with Antigravity on ArogyaTrack (10 October 2026)

**Setup.** Antigravity CLI 1.1.9, model `gemini-3.8-flash-medium`, repository `Aashutosh-Mahajan/ArogyaTrack` at commit `dbd5f1e` (710 tracked files), real sessions only (no mock). Each session ran in a fresh copy of the repository that was deleted afterwards; the original was never touched. Hooks were off. The prompt was identical across arms except one arm block.

- **No Prism:** ordinary Antigravity tools only; no Prism on PATH.
- **Prism CLI:** the agent runs `prism task "<request>"`.
- **Prism MCP:** the agent calls the native `prism_task` tool (lean profile), registered in Antigravity's MCP config for that session only and restored afterwards.

**Tasks (same four in every run).**

| Task | What the agent had to do | Check |
|---|---|---|
| t0 understand | Explain the architecture and where doctor validation and the AI data preparation live, without editing | Keyword check on the answer (4 of 5 expected facts), no files changed |
| t1 age rule | Minimum doctor age 23 → 25: validators (two modules), the experience formula, serializer comment, frontend message and limit | 8 hidden tests |
| t2 WEBP | Accept WEBP medical certificates in both validators, keep the 10 MB limit | 4 hidden tests |
| t3 severity | Add a "Critical" label for severity 6 and above | 8 hidden tests |

**Correctness: every one of the 36 sessions passed its check** (all three arms, all three runs).

## Tokens used by each arm — final run (same day, current Prism)

"Fresh input" is the new input tokens Antigravity reports; "cache read" is context re-read from cache on later steps (the two are added to get everything the model processed).

| | No Prism | Prism CLI | Prism MCP |
|---|---:|---:|---:|
| Fresh input | 621,377 | 460,332 (**−25.9%**) | 509,488 (**−18.0%**) |
| Cache read | 10,681,318 | 4,979,819 (−53.4%) | 7,092,568 (−33.6%) |
| **Total processed** | 11,302,695 | 5,440,151 (**−51.9%**) | 7,602,056 (**−32.7%**) |
| Output | 75,809 | 49,481 (−34.7%) | 57,995 (−23.5%) |
| Agent time | – | −32% | −31% |
| Sessions passed | 4/4 | 4/4 | 4/4 |

Per task (fresh input): understanding −6% CLI / −10% MCP; age rule −16% / −9%; WEBP −33% / −20%; severity label −40% / −34%.

## All three runs

| Run | Prism | Baseline fresh / total | CLI fresh / total | MCP fresh / total |
|---|---|---:|---:|---:|
| 1 (9 Oct) | frozen, before fixes | 995,312 / 13.53 M | 687,371 / 9.20 M (−30.9% / −32.0%) | 776,917 / 11.04 M (−21.9% / −18.4%) |
| 2 (10 Oct, prism arms only; baseline from run 1) | after trust fixes | (run-1 baseline) | 599,332 / 7.97 M (−39.8% / −41.1%) | 517,535 / 7.57 M (−48.0% / −44.1%) |
| 3 (10 Oct, final) | current | 621,377 / 11.30 M | 460,332 / 5.44 M (−25.9% / −51.9%) | 509,488 / 7.60 M (−18.0% / −32.7%) |

**Pooled over all runs** (baseline n=2, CLI n=3, MCP n=3, one session per cell): mean fresh input — baseline 808 k, CLI 582 k (**about −28%**), MCP 601 k (**about −26%**); mean total processed — baseline 12.4 M, CLI 7.5 M (**about −39%**), MCP 8.7 M (**about −30%**).

## What this does and does not show

- Prism used fewer tokens than no Prism in every arm, every phase and every run, with no loss of correctness on these four tasks. The CLI was ahead of MCP in the final run.
- **The 70–75% target was not reached.** Fresh input, the most conservative measure, is down roughly 18–40%; total processed is down 33–52% depending on the run.
- **Noise is large.** The no-Prism baseline itself moved from 995 k to 621 k fresh input between two days on the same tasks (the age task alone: 503 k then 232 k). With one session per cell, run-to-run differences cannot be attributed to the fixes. The earlier "improvement" from run 1 to run 2 was partly baseline noise because run 2 reused run 1's baseline.
- Every session carries a large fixed Antigravity prompt (about 17–30 k tokens), which no Prism change can reduce.
- Four small tasks on one repository and one model say nothing about other codebases, models or hosts.

## What changed in Prism and why it should matter

See `docs/trust-and-token-fixes-2026-10-10.md`. The finding that drove the last change: after receiving Prism's packet, the agent still ran `git grep "23"` across the repository because Prism's "exhaustive" list covered only parsed code. The 23 also appeared in translated locale files and i18n seed files. Prism now also searches text and data files (JSON, YAML, Markdown, HTML, `.po`, `.dart`, …) for the old value, so the age-task packet lists all 18 sites in 10 files as exhaustive instead of 12 sites in code only.

## Verification

- Unit and integration tests, ruff, mypy: pass (19+ new regression tests).
- Local reliability matrix, areas run: indexing and freshness 23/23, CLI 18/18, MCP 25/25, repeated sessions 2/2. Not yet run: retrieval, budgeting, cache, parity, hooks, isolation, robustness, optional features.
- Four reliability checks were found to be wrong themselves and corrected (details in the fixes note).

## Not done

Of the 28 planned items: the trust and correctness block, the edit-ready verdict, verify mode and the text-file search are done. Not done: semantic-retrieval changes, the narrative layer, automatic test selection, learned ranking feedback, deeper Dart/Kotlin parsing, a prompt-hook preflight experiment, Codex and Claude Code runs, repeated sessions with confidence intervals, and the three-repository, 32-task confirmation study from the benchmark kit. Query latency is about 1.3 s per CLI call on this repository (about 0.9 s before the text search), above the 200 ms target.
