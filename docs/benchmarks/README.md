# Prism reusable benchmark kit

Version 1.0 — 9 October 2026. This kit defines future experiments; it contains no new measured results.

Start with [the protocol](protocol.md), copy [the campaign template](campaign-template.md), then fill [campaign.json](campaign.json) and [tasks.template.json](tasks.template.json). Use [prompts.md](prompts.md) for agent instructions and [report-template.md](report-template.md) for results. Record every attempt using [attempts.csv](attempts.csv), every local build using [builds.csv](builds.csv), and every deviation using [deviations.csv](deviations.csv).

Keep completed campaigns in separate directories. Never overwrite a prior report. The JSON files are editable specifications, not an implemented execution harness. No agent experiments are launched by this kit.

Use [usage-events.csv](usage-events.csv) for response-level accounting and [data-dictionary.md](data-dictionary.md) for validation and aggregation rules.

The older [generic protocol](../agent-benchmark-protocol.md) is background material focused mainly on code localisation. This protocol adds real editing, native transports, setup amortisation, session reuse, and Prism reliability testing. Do not run the older analysis script unchanged: its missing-pair filtering is unsuitable for the failure policy here.

## Offline Phase 7 diagnostics

Run the labelled retrieval set without launching agents:

```sh
python -m tests.benchmarks.retrieval_eval --tier all --json
python -m tests.benchmarks.retrieval_eval --tier all --semantic --json
```

The semantic mode requires the default MiniLM model already on disk and fails explicitly if it
cannot load. Both modes report complete packet coverage, source-window top-three location recall
and estimated packet tokens. These measure retrieval, not a coding agent's cost or correctness.

For balanced development-session JSONL, the repository now ships a diagnostic analyzer:

```sh
python -m tests.benchmarks.agent_stats results.jsonl --output report.json
```

It resamples tasks and matched repetitions, rejects missing/duplicate cells and unknown usage,
keeps failed-session tokens, and reports observed pass^k, tokens per solved task, and separate
fresh input, processed input and total input-plus-output metrics. Missing hook delivery remains
unknown. The default 95% intervals and equal-task estimand are for development diagnostics;
the confirmation campaign must retain its preregistered equal-repository estimand, multiplicity
adjustment, retry consolidation and blind scoring. Do not substitute this script for that analysis.

## Reuse workflow

1. Copy this directory to a new campaign directory outside every subject checkout and its indexed roots.
2. Fill all `REQUIRED` fields and replace the task example with reviewed tasks. Freeze repositories, prompts, task keys, configuration, scoring rules and analysis implementation using SHA-256 manifests.
3. Run local reliability tests and a disjoint calibration pilot. Estimate the necessary sample size and total budget; freeze the main schedule before execution.
4. Run the main study under the protocol, retaining all attempts, errors and raw usage events.
5. Validate accounting, score blind, run the frozen analysis, and fill the report. Publish failures and limitations beside savings.

The recommended heavy campaign has **864 primary sessions**: 3 repositories × 32 tasks × 3 repetitions × 3 arms. Extra delivery, session, and generalisation experiments have separate counts and budgets.
