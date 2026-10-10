# PRISM Phase 7 — ArogyaTrack Codex benchmark

Completed 60 real Codex CLI sessions on `gpt-6-luna`, medium effort. Existing Claude Round 3 conditions: four tasks × five setups × three repetitions, six sessions at a time.

Repository: Aashutosh-Mahajan/ArogyaTrack, commit `a2e13f59ec107fa87b7531a1813e0606f870bbe8`. Each session used a fresh isolated copy, private Codex configuration, frozen PRISM source, a native Windows workspace-write restricted-token sandbox, and blocked network for generated shell commands. No original ArogyaTrack source was edited.

Tasks: architecture orientation; doctor minimum age 23→25 across rules, derived experience limits and messages; case-insensitive WEBP support in both certificate validators while preserving existing formats and the 10MB limit; severity mapping 1–2 Mild, 3–4 Moderate, 5 Severe, 6+ Critical.

| Setup | Passed / 12 | Fresh input change | Total token change | Tokens per solved session | Hook delivery |
|---|---:|---:|---:|---:|---:|
| baseline | 10/12 | +0.0% | +0.0% | 182,459 | 0% |
| cli | 10/12 | +6.3% | +27.9% | 233,287 | 0% |
| hook | 12/12 | -15.5% | -33.3% | 101,377 | 100% |
| mcp | 12/12 | -20.4% | -11.5% | 134,530 | 0% |
| mcphook | 11/12 | -27.7% | -39.4% | 100,597 | 100% |

Negative token changes mean fewer tokens than baseline. Total tokens include fresh input, cached input, and output. All scored failures remain in token denominators. Paired task/repetition bootstrap intervals (4,000 draws, seed 7), pass³, and per-task results are retained in the JSON and raw records. This small single-repository campaign does not establish multi-host or general 70–75% savings targets.

Orientation scoring is Claude’s existing keyword heuristic with a no-source-edit requirement, rather than an independently reviewed architecture answer. Edit scoring uses the existing hidden checkers against pristine repository copies after applying each candidate patch. The task prompt prohibits running a full application suite; these are targeted correctness checks, not ArogyaTrack integration tests.

Infrastructure attempts are preserved separately and excluded from treatment effectiveness comparisons because sandbox startup, denied MCP calls, incomplete MCP tool catalogs, or controller interruption changed the intended treatment. Their reported usage is included in attempt-accounting.json. Completed scored sessions were retained on resume; interrupted sessions were preserved and rerun in separate workspaces with separate event files. Interrupted sessions without a usage event have unknown cost, not zero; measured overall spending is therefore a lower bound. Recovered elapsed time is unavailable and is not used in token comparisons. No paid API pricing claim is made for subscription usage.

The sandbox write-boundary probe passed: writing in the allowed workspace succeeded, while writing to its parent was denied. MCP startup is mandatory and only the local prism_task tool has explicit approval. Vetted local hook execution remains enabled for hook treatments. Generated shell sandboxing remains active.

## Individual failed sessions

- t1_age / cli / repetition 1: FAILED hidden\test_t1_age.py::test_just_under_25_rejected[backend\patients\validators.py]; FAILED hidden\test_t1_age.py::test_experience_limit_uses_25 - assert ('age - ...
- t0_orient / mcphook / repetition 2: mentioned 3/5: ['django', 'next', 'flutter']; files changed: 0
- t2_webp / baseline / repetition 2: patch did not apply: error: No valid patches in input (allow with "--allow-empty")
- t2_webp / cli / repetition 2: FAILED hidden\test_t2_webp.py::test_webp_allowed_any_case[backend\patients\validators.py]; FAILED hidden\test_t2_webp.py::test_existing_types_and_limits[backend\patients\validators.py]
- t2_webp / baseline / repetition 3: FAILED hidden\test_t2_webp.py::test_webp_allowed_any_case[backend\patients\validators.py]; FAILED hidden\test_t2_webp.py::test_existing_types_and_limits[backend\patients\validators.py]

## Paired bootstrap uncertainty

| Setup | Fresh input change, 95% interval | Total token change, 95% interval | pass³ |
|---|---:|---:|---:|
| baseline | +0.0% to +0.0% | +0.0% to +0.0% | 75% |
| cli | -10.1% to +20.2% | +10.8% to +59.2% | 50% |
| hook | -50.1% to +32.3% | -63.2% to +13.0% | 100% |
| mcp | -44.6% to +9.6% | -44.3% to +32.9% | 100% |
| mcphook | -52.5% to +1.2% | -65.9% to -3.3% | 75% |
