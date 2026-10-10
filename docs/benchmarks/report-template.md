# Prism benchmark report: REQUIRED_CAMPAIGN

Date: REQUIRED. Status: NOT RUN / INCOMPLETE / COMPLETE. Frozen registration: REQUIRED.

## Verdict

CLI: REQUIRED. MCP: REQUIRED. Correctness: REQUIRED. Useful/large/very-large saving threshold supported: REQUIRED or none. State precisely which repositories, model, transport and delivery configuration this conclusion covers.

## Study accounting

| Item | Planned | Observed | Explanation |
|---|---:|---:|---|
| Repositories | | | |
| Independent tasks or sequences | | | |
| Assigned trials | | | |
| Completed trials | | | |
| Failed/time-limited trials | | | |
| Recovery attempts | | | |
| Trials with missing telemetry | | | |
| Native hook activation verified | | | |

## Inclusive measured totals

All values below include every attempt. Blank means unmeasured, never zero.

| Metric | Baseline | CLI | MCP |
|---|---:|---:|---:|
| Processed input | | | |
| Cached input, included above | | | |
| Uncached input | | | |
| Cache writes, provider semantics stated | | | |
| Output tokens | | | |
| Input plus output | | | |
| Actual cost, dated prices | | | |
| Proxy, if used and formula stated | | | |
| Verified successes / assigned trials | | | |
| First-attempt successes | | | |
| Total spend / verified success | | | |
| Median / p95 agent time | | | |
| Model turns | | | |
| Retrievals / fallbacks / duplicate deliveries | | | |

If there are no successes, cost per verified success is undefined; do not report zero.

## Paired inference

| Comparison | Primary input ratio | 97.5% interval | Success difference | 97.5% interval | Target passed? |
|---|---:|---|---:|---|---|
| CLI / baseline | | | | | |
| MCP / baseline | | | | | |

State task clusters, repetition count, repository weighting, bootstrap seed, missing-data treatment and power limits. Add per-repository/category tables and the largest token regressions. Successful-only comparisons are secondary and subject to selection bias.

## Knowledge lifecycle

| Cost component | CLI | MCP | Measurement boundary |
|---|---:|---:|---|
| Initial local build seconds / CPU / memory / disk | | | |
| Initial build model tokens | | | |
| Narrative authoring model tokens | | | |
| Refresh seconds and model tokens | | | |
| Agent editing tokens | | | |
| Lifecycle tokens at N=1/5/10/25/50/100 | | | Measured or projected? |
| Break-even edits: tokens / money / time | | | Assumptions and uncertainty |

## Reliability and causal diagnosis

Summarise matrix pass/fail evidence, CLI/MCP semantic parity, stale-index behaviour, session correctness, hook activation and full-build coverage. Explain token regressions using trace evidence. Separate local cache speed-ups from model-token savings.

## Charts

- Paired per-task ratios and CLI/MCP uncertainty intervals, with parity line.
- Correctness and latency beside savings.
- Input/cache/output breakdown with no double counting.
- Lifecycle totals versus number of edits; measured points distinguished from projections.
- Failure, fallback and redundant-read distributions.

## Limitations, deviations and reproduction

List every protocol change and when it was decided. Disclose missing data, unavailable builds, model/version drift, benchmark contamination, task selection and repository generalisation limits. Link frozen registration, hashes, raw evidence, scoring/adjudication, analysis source and reproduction instructions. Do not claim that smaller packets alone establish end-to-end savings.
