# Final report v2 — Prism fixes, Antigravity native integration, and the token results (10 October 2026)

Supersedes the earlier same-day report. Real Antigravity sessions only, model `gemini-3.8-flash-medium`, ArogyaTrack commit `dbd5f1e`, four tasks (understand the architecture; doctor minimum age 23→25; accept WEBP certificates; add a "Critical" severity label). Each session ran in a fresh copy of the repository that was deleted afterwards. Every one of the 56 sessions in this report passed its check.

## 1. Is the knowledge graph used?

Yes, by default: the **call graph** and **import graph** produce the callers, calls and impact lines in every packet, order candidates by PageRank, and drive the architecture map for explain-style requests (a small connected slice, 2 hops, 18 nodes). The **optional external Graphify export** (`graphify_graph` in `prism.toml`) is unset by default and was **not** used in any run. The viewer graph is separate from retrieval.

## 2. What was wrong, and what changed

See `trust-and-token-fixes-2026-10-10.md` for the first set. Added since:

| Finding | Fix |
|---|---|
| Names, numbers and messages that also live in translations, config, docs and templates were invisible to "exhaustive" lists, so agents grepped the whole repository | A text/data-file corpus (JSON, YAML, Markdown, HTML, `.po`, `.dart`, …) searched for literals and old values; the packet states its scope |
| Requests like "above 100 percent" were read as an old value | An old value needs an explicit change cue ("from N", "instead of N", "N to M") |
| Listed lines were whitespace-collapsed and cut at 110 characters, forcing agents to open files | Exact line text, up to 220 characters |
| Damaged SQLite caches crashed queries and blocked `scan` | Caches are disposable: purged and rebuilt once (CLI, MCP, hooks) |
| Junctions/symlinks pointing outside a repo were indexed | Links are not followed; links leaving the repo are skipped |
| `uninstall-integration` left empty directories; a declined prompt raised an internal error | Empty directories pruned; clean "Aborted" |
| The Antigravity integration wrote `.agent/rules/prism.md` with no trigger, which Antigravity does not load unconditionally; printed the wrong MCP config path; claimed hooks did not exist | Antigravity's own guide says `AGENTS.md` is always active, hooks exist (`PreInvocation`), and MCP lives in `~/.gemini/config/mcp_config.json`. Prism now installs an `AGENTS.md` block, a skill, and a `PreInvocation` hook (`prism hook pre-invocation`) that injects the packet as a persistent `userMessage` once per user request (an `ephemeralMessage` is dropped after one model call; injected steps are recorded as `SYSTEM_SDK` and ignored as requests) |

## 3. Token results

"Fresh" = new input tokens; "total" = fresh + cache reads (everything the model processed). One session per cell per run.

| Run | Prism setup | CLI | MCP |
|---|---|---|---|
| 1 | frozen, before fixes, kit prompt | −30.9% fresh / −32.0% total | −21.9% / −18.4% |
| 3 | fixes + text search, kit prompt, same-day baseline | −25.9% / −51.9% | −18.0% / −32.7% |
| 4 | "installed" (no hook), task-only prompt | −19.0% / −1.4% | −26.7% / −37.0% |
| 5 | **installed + hook** (native preflight) | **−41.8% / −65.3%** | – |
| 6 | installed + hook, repeat | −16.4% / −36.7% | MCP+hook −27.4% / −49.9% |
| 5+6 pooled | installed + hook | **−30.2% fresh / −53.1% total** | MCP+hook (run 6 only) −27.4% / −49.9%; pooled vs both baselines −33.9% / −57.1% |

Output tokens fell 30–40% and sessions ran 7–23% faster in the hook runs. Best single task: the age rule, −83% total (run 5). Weakest: −28% total (run 6).

**The 70–75% target was not reached on average.** Total processed tokens are down about 50–57% with the native preflight and about 30–34% on fresh input alone. Run-to-run noise is large (the same hook configuration saved 65% in run 5 and 37% in run 6), and the baseline itself moves by ±40% between days.

## 4. Why the rest remains, and the path to 70–75%

Total tokens ≈ model calls × context per call. In the weakest hook session the packet was injected and was complete, yet the agent re-opened the same files, then made about 25 of its own searches into areas the request never named (the mobile app, i18n extraction scripts, test discovery). Prism supplies a complete, trustworthy packet; it cannot stop an agent from exploring. Remaining levers, in order of expected value:

1. Hosts and models that trust an exhaustive scope statement (the packet now says what was searched and what was skipped).
2. A stop signal at the host level, for example a `Stop`/`PostInvocation` hook that runs the verify mode and ends the loop when no sites remain.
3. Cheaper context per call: the 17–30k-token fixed Antigravity prompt dominates; nothing in Prism can shrink it.
4. A larger, repeated study (3 repositories × 32 tasks × 3 repetitions per the benchmark kit) to establish the real average with intervals. Current results are single runs and show direction only.

## 5. Verification

Ruff, mypy `--strict`-style checks and the full unit and integration suite pass. Local reliability matrix: indexing/freshness 23/23, CLI 18/18, MCP 25/25, repeated sessions 2/2, hooks/consent/isolation/robustness/cache/budgeting/retrieval/parity/optional/network 27/27 (95 cases). Seven checks in the matrix were wrong themselves and were corrected (details in the fixes note); the rest of the failures were real Prism defects and are fixed.

## 6. Not done

Of the 28 planned items: the trust and correctness block, edit-ready verdict, verify mode, text/data search, scope statement, Antigravity native integration, cache recovery, link safety and the hooks/consent/isolation/robustness matrix are done. Not done: semantic-retrieval changes, a narrative layer beyond what exists, automatic test selection, learned ranking feedback, deeper Dart/Kotlin parsing (Dart files are now searched for literals but not parsed for symbols), Codex and Claude Code runs of the benchmark, the three-repository confirmation study, and a latency target: a warm CLI query is about 1.3 s on this repository (about 0.9 s before the text search), above the 200 ms goal.
