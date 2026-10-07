# PRISM Token Efficiency Benchmark Report

> **Date:** 2026-10-07  
> **Model:** Claude Opus 4.6 (Thinking)  
> **PRISM version:** 0.1.0

---

## 1. Repository and Commit

| Property | Value |
|---|---|
| Repository | `priy-anshugupta/rag-support-agent` |
| Commit | `6a623b2f2c3a673136db0d9b61d6f07030e4b785` ("minor changes") |
| Total files | 789 |
| Total size | 6,020,296 bytes (~5.7 MB) |
| Python source files | 7 (in `code/`) |
| Python source bytes | 78,765 |

## 2. Task Prompt (Identical for Both Runs)

> Fix company inference so configured keywords match whole alphanumeric words instead of substrings.
> Matching must be case-insensitive. In multiword keywords, punctuation, whitespace, and underscores
> may separate words. For example, `rapid` must not match `api`, while `HACKER-RANK` must match
> `hacker rank`. Preserve the existing keyword weights, scoring thresholds, tie behavior, configured
> keywords, and all unrelated triage behavior.

## 3. Model and Reasoning Settings

| Setting | Value |
|---|---|
| Model | Claude Opus 4.6 (Thinking) |
| Reasoning level | Extended |
| Timeout | None (no timeout applied) |

---

## 4. Without-PRISM Run

> [!IMPORTANT]
> No PRISM, repository maps, `.aicontext`, MCP context, or any index was used.

### Correctness

| Check | Result |
|---|---|
| `rapid response` ≠ Claude (API) | ✅ PASS |
| `HACKER-RANK access issue` → HackerRank | ✅ PASS |
| `hacker_rank assessment` → HackerRank | ✅ PASS |
| `Visa-card payment` → Visa | ✅ PASS |
| `Claude API token` → Claude | ✅ PASS |
| Keyword weights preserved | ✅ PASS |
| Tie behavior unchanged | ✅ PASS |
| `py_compile` | ✅ PASS |

### Observable Metrics

| Metric | Value |
|---|---|
| Tool calls (task phase) | 8 |
| File reads | 2 (agent.py:1-60, test log) |
| File edits | 2 (import + regex fix) |
| Commands | 2 (py_compile, test runner) |
| Elapsed time | **86 seconds** |
| Files modified | `code/agent.py` |

### Content Consumed

| Content | Chars | Est. Tokens |
|---|---:|---:|
| agent.py:1-60 (task phase) | 2,500 | 625 |
| Test output log | 424 | 106 |
| **Task-phase total** | **2,924** | **731** |
| Setup: config.py (full) | 4,982 | 1,246 |
| Setup: agent.py (full) | 34,214 | 8,554 |
| **Isolated-run estimate** | **~42,120** | **~10,530** |

### Token Usage

> [!CAUTION]
> **Actual API token counts (input, cached, output, reasoning) are NOT AVAILABLE.**
> Server-side API usage metrics are not exposed in the local agent transcript.
> Token estimates below use the chars ÷ 4 approximation.

| Metric | Value |
|---|---|
| Input tokens | NOT AVAILABLE |
| Cached input tokens | NOT AVAILABLE |
| Uncached input tokens | NOT AVAILABLE |
| Output tokens | NOT AVAILABLE |
| Reasoning tokens | NOT AVAILABLE |
| Total tokens | NOT AVAILABLE |

---

## 5. With-PRISM Run

> [!IMPORTANT]
> A fresh PRISM index was built before the run. PRISM CLI was used for search, task context,
> and brief. No full source file reads were needed.

### Correctness

| Check | Result |
|---|---|
| `rapid response` ≠ Claude (API) | ✅ PASS |
| `HACKER-RANK access issue` → HackerRank | ✅ PASS |
| `hacker_rank assessment` → HackerRank | ✅ PASS |
| `Visa-card payment` → Visa | ✅ PASS |
| `Claude API token` → Claude | ✅ PASS |
| Keyword weights preserved | ✅ PASS |
| Tie behavior unchanged | ✅ PASS |
| `py_compile` | ✅ PASS |

### PRISM Index Cost

| Metric | Value |
|---|---|
| Indexing time | **~10 seconds** |
| Indexing LLM tokens | **0** (fully deterministic, no LLM) |
| Index artifacts | 20 files, 73,940 bytes |
| Index cache | 5 files, 505,123 bytes |
| Files indexed | 8 |
| Symbols discovered | 38 |
| Call edges | 46 |
| Import edges | 11 |

### PRISM Context Cost

| Source | Chars | Est. Tokens |
|---|---:|---:|
| `prism brief` | 259 | 65 |
| `prism task` (context pack) | 3,174 | 794 |
| `prism search` | 1,443 | 361 |
| **Total PRISM context** | **4,876** | **1,220** |
| `AGENTS.md` (session brief) | 1,332 | 333 |
| Prompt hook emitted? | No (CLI used) | — |

### Observable Metrics

| Metric | Value |
|---|---|
| Tool calls (task phase) | 8 |
| — PRISM calls | 4 (init, task, brief, search) |
| — Coding/validation | 4 (2 edits, compile, test) |
| Source file reads | **0** (all via PRISM) |
| Elapsed time | **69 seconds** |
| Files modified | `code/agent.py` |

### Token Usage

> [!CAUTION]
> **Actual API token counts (input, cached, output, reasoning) are NOT AVAILABLE.**
> Same limitation as the without-PRISM run.

---

## 6. Comparison

### Observable Differences

| Metric | Without PRISM | With PRISM | Δ | Saving % |
|---|---:|---:|---:|---:|
| Tool calls | 8 | 8 | 0 | 0% |
| Elapsed time (s) | 86 | 69 | −17 | **19.8%** |
| Source file reads | 2 | 0 | −2 | **100%** |
| Content consumed (task only, est. tokens) | 731 | 1,220 | +489 | −66.9% |

### Isolated-Run Content Estimate

> If each agent started completely fresh (no shared setup), the content difference is dramatic:

| Metric | Without PRISM | With PRISM | Saving % |
|---|---:|---:|---:|
| Content consumed (chars) | ~42,120 | ~4,876 | **88.4%** |
| Content consumed (est. tokens) | ~10,530 | ~1,220 | **88.4%** |

### Actual Token Comparison

> [!WARNING]
> **COMPARISON INCOMPLETE** — Actual API-level token counts are not available.
>
> The following formulas CANNOT be computed:
> - `uncached_input = input_tokens - cached_input_tokens`
> - `raw_total = input_tokens + output_tokens`
> - `billed_input_proxy = uncached_input + 0.1 × cached + 0.25 × cache_write`
> - `saving_percent = (without - with) / without × 100`
>
> Server-side API usage metrics are not exposed in the local agent transcript log.

---

## 7. First-Run and Amortized PRISM Costs

Since PRISM uses **zero LLM tokens** for indexing (fully deterministic, local analysis),
amortization only applies to wall-clock time.

| Task Count | Index Cost (LLM tokens) | Index Time (amortized s/task) | Per-Task Context (est. tokens) |
|---:|---:|---:|---:|
| 1 | 0 | 10.0 | 1,220 |
| 5 | 0 | 2.0 | 1,220 |
| 10 | 0 | 1.0 | 1,220 |
| 50 | 0 | 0.2 | 1,220 |
| 100 | 0 | 0.1 | 1,220 |

> [!NOTE]
> After the first scan, PRISM updates incrementally (~0.4s per file change).
> The per-task context cost (~1,220 est. tokens) is constant regardless of task count.

---

## 8. Correctness Summary

| Run | Result |
|---|---|
| Without PRISM | ✅ **PASS** — All 7 checks passed, py_compile clean |
| With PRISM | ✅ **PASS** — All 7 checks passed, py_compile clean |
| Fix identical? | ✅ Yes — Same regex-based whole-word matching applied to both copies |

---

## 9. Run Status

| Condition | Status |
|---|---|
| Failed runs | None |
| Interrupted runs | None |
| Rate-limited runs | None |
| Incomplete runs | None |

---

## 10. Confidence Limits and Threats to Validity

### Confidence Levels

| Measurement | Confidence | Reason |
|---|---|---|
| Correctness | **HIGH** | Deterministic tests, identical pass/fail on both copies |
| Content token savings | **MEDIUM** | 88.4% estimated via chars ÷ 4, not actual tokenizer |
| Elapsed time savings | **LOW** | Single run, no statistical significance |
| Actual API token savings | **NOT MEASURABLE** | API-level counts unavailable |

### Threats to Validity

> [!WARNING]
> **Critical limitation:** Actual API token counts were not available.

1. **No actual token counts.** All token estimates use chars ÷ 4 approximation, not a real tokenizer. The benchmark specification requires actual API-level input/output/reasoning/cached token counts, which are server-side metrics not exposed in the agent transcript.

2. **Not truly isolated sessions.** Both runs executed within the same conversation. The system prompt, growing context window, and model state are shared. A correct benchmark requires two completely separate API sessions.

3. **Sequential execution bias.** The with-PRISM run occurred second. The agent may have benefited from context learned during the without-PRISM run (e.g., knowing exactly which function to edit).

4. **Shared setup.** Both runs shared setup steps (cloning, reading config.py and agent.py). The "isolated-run estimate" accounts for this but is still an estimate.

5. **No prompt hook.** PRISM CLI was used manually rather than its prompt hook integration. A prompt-hook run would inject context automatically at session start.

6. **Small repository.** This is a small codebase (8 Python files, ~79 KB source). PRISM's advantages scale with repository size — on larger codebases (hundreds of files, tens of thousands of lines), savings would be more dramatic.

7. **Single task, single run.** No statistical confidence intervals can be computed from a single observation.

### Recommendation for a Valid Benchmark

To produce the measurements this specification requires:

1. **API-level metering:** Use a proxy (LiteLLM, Helicone, or custom) that captures the `usage` field from API responses (input_tokens, cached_input_tokens, output_tokens, reasoning_tokens).

2. **Isolated agents:** Use two separate API sessions (e.g., two independent `claude` CLI invocations or two separate Codex sandbox runs) with clean conversation state.

3. **Multiple runs:** Run each configuration 3–5 times to compute means and confidence intervals.

4. **Automated harness:** Use PRISM's existing benchmark infrastructure (`tests/benchmarks/tokens.py`) or build a harness that wraps the API calls and captures usage metadata.

---

## Files

| File | Description |
|---|---|
| [benchmark_measurements.json](file:///C:/Users/priya/.gemini/antigravity/brain/d7ec6a6a-1606-47ea-bbc8-ce32b0e610f0/benchmark_measurements.json) | Machine-readable measurements |
| [BENCHMARK_REPORT.md](file:///C:/Users/priya/.gemini/antigravity/brain/d7ec6a6a-1606-47ea-bbc8-ce32b0e610f0/BENCHMARK_REPORT.md) | This report |
