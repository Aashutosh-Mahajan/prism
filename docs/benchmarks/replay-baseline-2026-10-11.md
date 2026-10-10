# T00 retrieval baseline — 11 October 2026

The baseline harness and measurements are implemented and validated. No product
behavior has been changed as part of T00. Later Phase 0 changes are recorded
separately in the execution ledger.

## Reproduce

Run from the repository root. Pin this revision for later before/after comparisons;
letting HEAD advance would change the selected requests and historical source.

```powershell
python -m tests.benchmarks.packet_audit --ref 9f74f92151d655f308de08b165aa0fc6a239a983
python -m tests.benchmarks.replay_precision --ref 9f74f92151d655f308de08b165aa0fc6a239a983 --commits 40 --history 150
```

On this Windows sandbox, set TEMP and TMP to a writable scratch directory first.
Creating worktrees also requires permission to write Git metadata.

Both scripts use in-process `op_task`, budget 2,000, no semantic model, no packet
cache, isolated consent configuration, and scratch worktrees. They do not
initialize or scan the working checkout. JSON reports, including delivered
packets, are saved under gitignored `output/benchmarks/`.

The source revision was `9f74f92151d655f308de08b165aa0fc6a239a983`. The engine
included pre-existing uncommitted navigator edits, preserved during this task.
Its Python source fingerprint was
`564158b2250611a7f04b00bcf8438f72e671d45a0d36109fec2ba3a9d0de5e1f`.
This is a working-tree engine baseline, not a claim that clean HEAD produces
identical results. Reports record that distinction explicitly.

## Parent-commit replay

The most recent 150 non-merge commits yielded 40 eligible queries. Each query is
the commit subject without its Conventional Commit prefix. Subjects with
`docs`, `chore`, `ci`, or `test` types and queries shorter than four words are
excluded. Eligible commits change one to four Python files under `prism/`.
Each query runs against its own first-parent checkout using the current engine.

| Metric | Measurement | Denominator |
| --- | ---: | --- |
| File recall, all changed files | 16.39% | 10 / 61 files |
| Any-hit rate | 22.50% | 9 / 40 queries |
| Token precision | 18.86% | 4,492 / 23,814 estimated code tokens |
| Block-level recall | 7.95% | 24 / 302 parent-side hunks |
| Mean packet size | 1,013.18 estimated tokens | 40 queries |
| Runtime | 298.16 seconds | 40 queries including indexing |
| File recall, existing parent files only | 25.00% | 10 / 40 files |

Twenty-one target files did not exist in their parent checkout; eleven commits
introduce only new target files. They remain misses in the headline file metric.
The existing-file diagnostic is additional context, not a replacement metric.
New-file hunks have no old-side source and are excluded from block recall.
Pure insertions use the preceding parent line as an anchor where one exists.
Block recall requires the whole old-side range to have been delivered; a header
covering omitted source does not count.

All fenced source roles count, including definitions and implementation helpers.
Per-line numbering is removed before estimating code tokens. Literal occurrence
lists, callers, and recovery hints do not count as source blocks. Packet size
includes the entire rendered response. Estimates use ceil(characters / 4), not
provider token counts.

These numbers are substantially lower than the plan's earlier HEAD-index replay.
The historical source, selected commits, and scoring details differ. Do not
treat that earlier 62% recall / 37% precision result as this experiment's
before value, or infer agent token savings from either replay.

## Fixed ten-request packet audit

Request texts and their first source revision are fixed in
`tests/benchmarks/packet_audit_requests.json`. The current engine queried a
scratch checkout of the pinned source revision.

| Metric | Measurement |
| --- | ---: |
| Requests | 10 |
| Total characters | 52,672 |
| Mean packet size | 1,317.10 estimated tokens |
| Production source | 67.95% |
| Test source | 2.34% |
| Callers, including section headers | 9.29% |
| Source block headers, all roles | 6.73% |
| Next / Batch lines | 3.46% |
| Other text and fences | 10.24% |
| Per-line number prefixes | 6.50% |
| Test caller share of caller characters | 33.57% |
| Runtime | 13.79 seconds |

Composition categories are disjoint and sum to 100%; prefix characters are an
overlapping diagnostic. The rename request's test-source share is 19.72%, well
above the planned T13 cap of 3% on non-test requests. The test request about
`_store` returns only 142 estimated tokens; the per-request JSON retains this
outlier instead of dropping it from the mean.

## Validation and task status

- Thirteen new tests pass, covering source roles, CRLF and spaced paths,
  omitted lines, malformed fences, parent-side diff coordinates, scoring,
  disjoint composition, restored environment variables, pinned history,
  and an actual scratch worktree lifecycle.
- Ruff checks and formatting pass on the three new Python files.
- Strict mypy passes on both benchmark modules; `python -m mypy -p prism`
  also passes on 150 source files.
- `ruff check .` finds pre-existing SIM905 in
  `prism/navigator/delegation.py` and I001 in `prism/navigator/task_pack.py`.
  Those edits are preserved.
- `python -m mypy .` encounters an access-denied directory at
  `tmp/native-context-tests`; package-scoped checking passes as recorded above.
- The broad pytest and unit-suite runs stopped making visible progress and were
  interrupted. They are not reported as passing. The focused T00 tests completed.
- Both benchmarks ran offline in under ten minutes. Scratch worktrees were
  removed; the main checkout's source and consent state were not initialized.

Subsequent validation resolved the environment issues: the full suite passes
with loopback permissions and temporary fixtures outside the checkout. Repository
Ruff and strict package mypy also pass. The two lint issues were formatting-only;
the pre-existing functional edits remain intact. T02's provider measurement is
explicitly deferred by the owner; default token_scale remains 1.0.
