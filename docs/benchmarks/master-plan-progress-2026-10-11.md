# Master improvement plan execution

Owner requested the full plan on 11 October 2026. DevRelay MCP was removed first.
Existing uncommitted delegation/retrieval work is preserved and not included in
task commits. Codex gpt-6-luna using the existing subscription is authorized for
live measurements; paid API execution is not authorized. The owner explicitly
deferred Anthropic token-count measurement; token_scale remains 1.0 by default.

| Task | Status | Evidence / outstanding work |
| --- | --- | --- |
| T00 | committed | 5054b58; 40 parent replays in 298 s; fixed 10-request audit; 13 tests |
| T01 | committed | e61ef6e; token classes, pricing branches, pass@1/pass^k, dollars and frozen-cache costs; original 60-session pass counts unchanged |
| T02 | implemented; measurement deferred by owner | optional deterministic scale, 50-sample manual harness; no credential configured; default 1.0 |
| T03 | committed | 2b43f51; root 142 lines / 1,497 estimated tokens; verbatim linked specifications and short nested rules |
| T04 | committed | c59bc78; 9,500-character cap through smaller retrieval budget; doctor warning and ADR 0006 |
| T05 | committed | 22c18c2 + 5755671; specific patch refusal codes; six safety branches tested plus cache failure |
| T10 | committed | da42c72; 80-site checked compact patch; 450-site refusal; replay recall and precision unchanged |
| T11–T15, T16a | accepted; commit pending | final replay precision 20.0339%, file recall 14.7541% (within 2 points), mean 624.725; format saving 13.3349%; adaptive audit 681.9; parity and offline suite pass |
| T16b | pending, later persisted form | schema version, migration and scan/update equivalence still required |
| T20–T30 | pending | experiment-dependent defaults remain unchanged |
| T40–T48 | pending | subscription campaign and optional experiments still required |

Validation environment: sandboxed Windows asyncio stalled creating its loopback
socket pair. Tests run with local loopback access but retain the external-network
blocker. Temporary fixtures must be outside this Git repository; otherwise fixture
copies inherit its Git/index state. The three failures from workspace-contained
temporary files passed individually with corrected isolation.

Phase 0 automated validation passes: full offline suite, Ruff and strict package
mypy. T02 API measurement is deferred by owner approval. Claude Code 2.1.296 /context now confirms project CLAUDE.md at 2.3k tokens
and total memory at 2.4k, with MCP disabled and no session persistence. No startup
length warning was emitted. T02 commits: 33257ea + 08d7c4c. Phase 1 is in progress.
Do not interpret implementation as
acceptance where live, manual or regression measurements are still outstanding.

Owner changed the Phase 1 precision gate to improvement over the pinned measured
baseline (18.86285%), preserving the original recall and size requirements.
The 55% absolute target is no longer the acceptance gate. First selector replay:
11.6889%; matched-excerpt replay: 15.9708%; two-candidate edit replay: 18.0650%.
None passes the precision gate. Final compact-format replay passes: 20.0339% precision, 14.7541% recall, mean
624.725 estimated tokens.

T14 smoke pilot: gpt-6-luna, Codex CLI, ChatGPT login, API credentials removed,
no paid API authorization. One isolated small fixture, segment-only source line
numbering, successful edit and three independent assertions; 33.86 seconds.
This is a formatting check, not a T41 benchmark arm. Raw pilot events are under
output/benchmarks/format-pilot; native reported input 100,983, cached input 85,760,
output 536, reasoning output 82. These are subscription usage, not a dollar bill.

T21 is implemented locally with thirteen passing output-filter tests, but is
not marked accepted as a phase milestone while the Phase 1 gate is outstanding.

Final-format audit: 37,803 legacy characters vs 32,762 compact characters,
13.3349% savings for identical parsed source blocks and delivered lines.
Latest adaptive audit: 681.9 estimated tokens, zero test-source characters and
zero test callers on non-test requests. Final replay and full offline suite pass.
The sufficient rate is 2/10 for both fixed and adaptive budgets after selection
changes; T00 was 3/10. The ladder itself did not reduce this rate.

Caller oracle: all six production call sites for build_task/render_task in the
pinned repository are delivered, plus the independent fixture source oracle.
A final focused test verifies the inferred-caller limit is three across the
whole packet, with resolved callers retained for both targets. Earlier replay
packets had at most one delivered inferred caller; audit packets had none.
All refusal codes now have coverage, including generic_name and budget_exceeded.
