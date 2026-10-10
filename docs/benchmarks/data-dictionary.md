# Measurement contracts

These CSV files are blank templates. Populate them with measured data, not agent estimates. Add schema-versioned columns if a provider needs additional billed categories.

- `usage-events.csv`: one normalised delta row per unique provider response per attempt. Deduplication key is `(trial_id, attempt_id, provider_response_id)`. Preserve raw cumulative events separately. `usage_semantics` identifies the original provider accounting and normalisation rule.
- `attempts.csv`: one row per attempt; sum its usage rows once. `trial_id` identifies campaign/experiment/repository/task/repetition/arm. `attempt_id` is unique within it. `attempt_kind` is initial or infrastructure_recovery. Status is succeeded, failed, timeout, prelaunch_failure or telemetry_missing. `verified_success` is a boolean evaluator result, not the agent's assertion.
- `builds.csv`: one row per measured setup, narrative_authoring, refresh, query_cold or query_warm operation. Do not add diagnostic benchmark query loops to the product lifecycle cost unless that workload actually uses them. Associate shared build costs with a declared lifecycle, not once per trial by accident.
- `deviations.csv`: append-only record of changes to the frozen design.

Store UTC timestamps in ISO 8601. Durations are seconds. Token counts are nonnegative integers. Empty fields mean unavailable; measured zero is `0`. Boolean fields use `true`/`false`. Currency uses an explicit code. Never put API credentials in these files.

Where cached input is included in input, verify `uncached_input = processed_input - cached_input`; separately reconcile any provider cache-write categories. Reasoning tokens labelled as an output subset must not be added to output again. Unknown provider semantics block monetary claims until resolved.

Trial aggregation sums all attempts' tokens/time. Trial eventual success is the final evaluated result under the registered recovery policy; retain first-attempt success separately. Campaign trial counts come from the frozen schedule, including entries that failed to launch. Provider-response totals must match attempt totals and report totals.

Before analysis, reject duplicate keys, unknown arms, unregistered tasks, negative counts, impossible cached/input relationships, missing source hashes and unmatched planned trials. Flag missing counters for explicit reconciliation; never coerce them to zero. Zero baseline input makes a ratio undefined; report the affected scope rather than silently dropping it.

The JSON campaign/task files are specifications; they are not executable schemas or a ready runner. Required null limits and `REQUIRED` fields intentionally prevent a draft from being mistaken for an execution-ready campaign. Implement and validate the runner and analysis against this contract before launching confirmation.
