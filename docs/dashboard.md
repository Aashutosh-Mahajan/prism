# Local dashboard

Start an indexed repository with `prism view --root <repository>`. Open the complete authenticated URL printed by the command. The new default page is `/dashboard.html`; `/` still serves the original graph viewer. A graph focus URL continues to open that viewer directly.

The local workspace includes:

- **Compare:** side-by-side recorded solutions, independent checks, raw provider usage, fresh-token changes, trace/code tabs and patch exports.
- **Repository:** actual source commit/branch, index coverage, consent/freshness and an explicit background refresh.
- **Context:** the existing `op_task` engine, exact readable/JSON packet, copy and download. Preview requests have no agent delivery session.
- **Graph:** the existing viewer and graph backend, embedded within the workspace. Offline standalone graph exports continue to work.
- **Runs:** imported evidence persisted under `.aicontext/cache/dashboard/runs/`.
- **Settings:** Codex, Claude Code and Antigravity executable detection and capability status.
- **Separate repository copies:** prepare matching committed source copies outside the original repository, then index only With PRISM. No agents are launched by this action.

Light, dark and system themes are available. Assets and fonts are bundled locally. No source edits or model calls occur when opening the dashboard, exploring the graph or retrieving context.

## Current execution limit

Managed agent execution is not implemented in this first workspace increment. The Run comparison action is disabled and explains the missing validated isolation/provider adapter. Installation detection alone is not proof of authentication, hooks, permissions or usable counters. No live token-saving claim is made.

The next implementation gate in `ui.prd` is a working Codex adapter with enforced isolation, permission probes, fresh histories, automatic delivery proof, complete counters and independent checks. Other hosts require their own validated adapters. Existing repository-specific benchmark scripts are not exposed as a generic runner.

## What separate sandboxes mean

Without PRISM and With PRISM need different working directories and new agent histories. They start from the same source commit, task, model and independent checks. Only the With copy receives PRISM's index/integration. Neither agent should read the other solution, evaluator, previous reports or your original repository.

**Prepare copies** freezes HEAD and task text, extracts two matching sources, verifies checksums, builds the real PRISM index in With only, and records build time, coverage and zero LLM calls for deterministic indexing. Uncommitted edits are excluded and left untouched. Host configs/caches, secret environment files and credential files are excluded from both. Symlinks and submodules require a separate adapter and are rejected. Copies and preparation manifests are under the user config directory `dashboard-benchmarks/<id>/`; failed attempts are retained.

Separate folders protect originals from ordinary editing, but are not an enforced execution sandbox. OS permissions/container/VM isolation, dependencies, evaluator protection, actual hooks, provider authentication/counters and live agents remain pending. The UI displays this and keeps live execution disabled. Preparation never generates a token-saving result.

## Staying synchronized with the core

Dashboard previews run the same consent-aware `refresh_if_stale` step as CLI/MCP before `op_task`. Pausing PRISM keeps automatic refresh paused. Previews are excluded from agent activity/delivery records. The response includes the actual index revision and scan date used for the packet.

Repository status is periodically refreshed while the page is visible and when opening repository/graph pages. The graph iframe is the existing viewer, which listens to the core's index events. Both graph and context use the same `.aicontext` generation. Dashboard refresh uses the existing lifecycle scan/lock; its job is persisted. On a server restart, unfinished jobs show Interrupted and are not silently rerun.

## Evidence report format

Use **Download report template** on Compare. It deliberately contains empty checks and unknown usage. Fill it with actual campaign evidence, then import JSON. The schema is version 1:

- `configuration`: repository, full source_commit, task, host, exact model, reasoning and delivery method.
- `arms.without` and `arms.with`: actual effective configuration, completed/failed/interrupted/cancelled status, independent checks, elapsed_seconds, trace and patch.
- Each usage record: response_id, measurement=`provider`, input_tokens, cached_input_tokens, output_tokens and total_tokens.
- `session_usage`: the same four final counters; must reconcile with deduplicated response sums.
- Each independent check includes `name`, `passed`, `independent=true` and the frozen evaluator's `evaluator_sha256`. Both arms must use identical check names and checksums.
- `evidence`: isolation_verified, baseline_prism_absent, matching_source_verified, and hook_context_delivered when using a hook.

Cached input is a subset of input under this schema. Total is input + output. Output includes reasoning; reasoning is not added again. Counters from a provider with other definitions require a normalization adapter before import. Unknown fields stay unavailable.

Failure, missing usage, unmatched effective settings, different checks or missing integrity evidence prevents comparable-success savings. Increased token usage remains an increase. A zero baseline produces undefined savings. Raw savings and uncached-input-plus-output changes are separate; neither is automatically a billing estimate.

Reports reusing the same provider response identity in both arms are not comparable. Saved reports are revalidated when opened so an old cached summary cannot override updated validation rules.

Imported assertions are supplied by the report author. Consistency validation does not authenticate their provider origin, isolation or evaluator. The UI labels the provenance and retains this limitation in exported evidence. One pair cannot establish typical savings.

Patch export downloads supplied changes for normal Git review/application. This workspace does not apply source changes or create commits. Report exports can be reimported. Context exports are exact packets, with size estimates labeled separately from actual provider usage.

## Development and checks

In `viewer/`, install dependencies using `npm ci`, build with `npm run build`, and run `npm test`. Build creates two independent bundles: the existing viewer and the dashboard, retaining the self-contained graph export contract.

Python verification includes `tests/integration/test_dashboard.py` and the existing viewer tests. Dashboard endpoints share existing localhost token/cookie and Host checks. Browser mutations additionally reject cross-origin requests. The graph permits same-origin embedding; dashboard documents remain unframeable.
