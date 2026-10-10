# Phase 7 implementation and validation — 10 October 2026

Scope: the actions in [the research deep dive](research-deep-dive-2026-10-10.md)
and Phase 7 in [the update plan](../update.md). Existing uncommitted implementation
was preserved. This follow-up closes test weighting and semantic evaluation and
hardens the implemented packet, patch, hooks and benchmark diagnostics.

## Additional fixes

| Area | Defect and resulting behavior |
|---|---|
| Read dedupe | PreToolUse previously remembered attempted reads. PostToolUse now confirms actual returned text against the file and records only returned lines. Denied/failed reads and unknown/binary response formats remain readable. SessionStart clears coverage after resume/compaction; new reads do not extend old coverage's expiry. |
| Test selection | Callers are walked breadth-first, up to three hops and 64 symbols, with direct tests before indirect tests and name/import/folder fallbacks. Low-confidence edges are excluded. Unmapped test files are included; absence is disclosed. Tests are selected across primary symbols. |
| Test commands | An unrelated subproject's runner could strip arbitrary prefixes from test paths. It now returns no command in that case, and shell-quotes paths containing spaces. |
| Git consent boundary | An explicitly indexed nested folder could install hooks in its ancestor Git repository. It no longer does. Root discovery also stops at a nested Git/worktree boundary before an ancestor index. |
| Checked patches | Git can exit successfully after skipping all paths when invoked in a subfolder. Diffs now include the worktree prefix, and checking requires nonempty numstat output as well as a successful applicability check. CRLF and missing final newlines remain byte-exact. |
| Numeric substitutions | Decimal prefixes are preserved. Simultaneous replacements cannot cascade. A value can be both a destination and another old value; distinct old values on the same source line retain their evidence. Conflicting destinations or missing requested substitutions produce no patch. |
| Large-file reads | Scattered sites could merge into a whole-file span. Hints now remain at most 120 lines, with bounded windows per file. The literal list remains authoritative for additional sites beyond the hint cap. |
| Statistics | The external development analyzer advertised task resampling but only resampled sessions within fixed tasks. The shipped diagnostic resamples tasks and matched repetition pairs, rejects missing/duplicate cells and unknown usage, retains failure tokens and includes output tokens in total spend. |
| Concurrent viewer refresh | A Windows artifact-open sharing denial surfaced as HTTP 500 during refresh. JSON readers now retry PermissionError briefly, as atomic writers already do; permanent denials and corrupt JSON still raise. Viewer artifact reads use the shared reader. |

## Offline semantic evaluation

The installed `sentence-transformers/all-MiniLM-L6-v2` ran locally through the NumPy
encoder; nothing was downloaded. The evaluation forces lexical or semantic mode
explicitly, warms vectors before queries and fails if the semantic model cannot load.
Cases and expected locations were unchanged.

| Metric | Lexical | Lexical + semantic |
|---|---:|---:|
| All 22 requests: complete expected locations in packet | 18/22 (81.8%) | 20/22 (90.9%) |
| All expected locations covered | 86.7% | 93.3% |
| Mean estimated packet tokens | 610.2 | 639.0 |
| Eight paraphrases: complete expected locations in packet | 5/8 (62.5%) | 7/8 (87.5%) |
| Eight paraphrases: top-three source-window location recall | 62.5% | 75.0% |

Top-three recall here means the expected location occurs inside one of the first
three returned source blocks, independently of literals or caller lines. The +12.5
percentage-point gain on paraphrases meets the planned +10-point local retrieval
gate on this small labelled set. It does not establish live-agent token savings or
generalization to external repositories.

Reproduce:

```sh
python -m tests.benchmarks.retrieval_eval --tier all --json
python -m tests.benchmarks.retrieval_eval --tier all --semantic --json
```

Raw results are retained in `docs/benchmarks/phase7/`. The benchmark README describes
the shipped diagnostic analyzer and its separation from the confirmation protocol.

## Validation

- Final full offline suite: **543 passed**, 224.14 seconds, including the seven
  statistical diagnostic regressions and multi-value patch regressions.
- The final Windows JSON-reader fix additionally passes **21 targeted tests**:
  all 18 viewer backend tests plus three new reader regressions. Permanent errors
  and corrupt JSON remain visible; the concurrent index-refresh test passes.
- Ruff lint and formatting pass; strict mypy passes across 139 source files.
- Viewer: 20 tests pass; typecheck and production build pass.
- Offline wheel build and installation pass. Isolated import smoke confirms the installed
  package, MCP/patch/hook modules, viewer JavaScript and context skill are present.

The complete suite runs in temporary repositories outside this checkout. Running
its uninitialized fixture tests under this indexed Git repository exposes ancestor
index/history and invalidates their isolation assumptions. Sandbox filesystem and
process restrictions also affected early validation attempts; final verification
uses normal local process access with test-network blocking retained.

## Remaining external acceptance work

| Item | Status and prerequisite |
|---|---|
| Live multi-host, multi-repository campaign (7.9/7.17) | The owner-authorized [ArogyaTrack Codex Luna campaign](benchmarks/phase7/codex-luna-arogya-2026-10-10.md) completed 60 sessions under Claude's existing three-repetition design. The broader campaign still needs Java/Go and TypeScript repositories, reviewed tasks/oracles, frozen host/model configurations and a budget. Research asks for at least five repetitions; these three repetitions do not satisfy that broader gate. |
| Clearable results (7.7) | Native MCP returns tool results. Clearing history is controlled by the host; no supported PRISM hook API was identified for it. Prompt injection cannot promise clearability. |
| Claude partial-read-before-edit behavior (7.6) | Read ranges are built/tested, but actual host acceptance needs a native-host trial. |
| Test selection effectiveness (7.12) | Direct, indirect and unmapped fallback regressions pass. The >=90% external seeded-bug criterion needs a frozen independent dataset. |
| Session-level savings and correctness targets | Twin-task pass rate, reduced model calls/read calls, first-call overhead and 70–75% total saving require live measurements. No such claim is made from the offline tests. |
| Cross-platform hosted CI | Local Windows validation is complete; hosted Linux/macOS results are not available from this run. |

## Community evidence

[Yugesh Jha's development report](https://dev.to/yugesh_jha_4493f0f45525c1/cost-per-token-is-the-wrong-number-for-coding-agents-heres-what-we-measured-instead-1fp5)
argues for repeated tasks and cost per completed task. Its comments question whether
verification and failed escalation attempts are included. This is one team's reported
experience, not evidence for PRISM's effectiveness; the diagnostic here explicitly
counts failures and keeps correctness beside tokens.
