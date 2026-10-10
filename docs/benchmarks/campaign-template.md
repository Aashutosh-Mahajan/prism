# Campaign registration: REQUIRED_NAME

Status: DRAFT. Replace every REQUIRED entry before main execution.

## Freeze sheet

| Field | Value |
|---|---|
| Campaign ID/date/owner/reviewer | REQUIRED |
| Protocol version and SHA-256 | REQUIRED |
| Prism commit and dirty-diff hash | REQUIRED |
| Model, effort, sampling, host/harness version | REQUIRED |
| Repositories, commits, source manifests, sizes/languages | REQUIRED |
| Dependency lockfiles and runtime/container image hashes | REQUIRED |
| Task suite / hidden key / prompt / scoring hashes | REQUIRED |
| Analysis code version and hash | REQUIRED |
| Arms and exposed tool/schema manifests | REQUIRED |
| CLI/MCP/hook configuration, session rules | REQUIRED |
| Cold/warm index and provider cache regimes | REQUIRED |
| Tasks / repetitions / power simulation | REQUIRED |
| Seed / schedule hash / execution order policy | REQUIRED |
| Per-trial time, turns, tokens; campaign spend ceiling | REQUIRED |
| Primary metric and weighting | Equal-repository-weighted processed-input mean ratio |
| Correctness endpoint and margin | Verified success; -0.05 |
| Useful / large / very large ratio thresholds | 0.80 / 0.50 / 0.30 |
| Interval and comparison family | 97.5% two-sided; CLI/B and MCP/B |
| Latency guardrail | REQUIRED |
| Failure, retry, missing-data policies | Protocol sections 7 and 9; list any changes |
| Local build / narrative / refresh boundaries | REQUIRED |
| Pricing or proxy rules and source date | REQUIRED, or no currency claims |
| Accepted limitations and deviations | REQUIRED |

## Gates

- [ ] Reliability matrix completed; no unresolved critical failures.
- [ ] Subject baseline tests pass and verification environment is available.
- [ ] Hidden tests fail the seeded bug and pass a valid implementation.
- [ ] Agent copies cannot access keys, reports or other trial state.
- [ ] Baseline has ordinary efficient discovery and no Prism leakage.
- [ ] Native CLI/MCP smoke tests and usage parser hand-audit pass.
- [ ] Calibration tasks are disjoint from confirmation tasks.
- [ ] Power and total budget reviewed; hard stop semantics recorded.
- [ ] Registration, schedule and analysis frozen before main outcomes.
- [ ] Blind reviewer and evidence archive ready.

## Per-trial checklist

- [ ] Record source/config hashes and index state before start.
- [ ] Start fresh agent/session and arm-specific isolated environment.
- [ ] Capture raw response IDs, usage events, tools and errors.
- [ ] Retain every attempt, patch and validation log.
- [ ] Evaluate in an isolated copy; record success and blind review.
- [ ] Stop child servers; preserve evidence; do not reset other trials.

## Completion checklist

- [ ] Reconcile planned/started/completed/failed/missing trials.
- [ ] Recompute tokens independently; explain every missing event.
- [ ] Analyse the fixed sample and both transports, retaining failures.
- [ ] Include lifecycle costs, confidence intervals and all deviations.
- [ ] Publish the report with immutable evidence references.
