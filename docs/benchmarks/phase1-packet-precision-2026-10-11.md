# Phase 1 packet measurements — 11 October 2026

The owner replaced the plan's absolute 55% precision gate with improvement over
the pinned parent-commit baseline, keeping the original recall and size gates.
Source history is pinned to 9f74f92151d655f308de08b165aa0fc6a239a983. These are
commit-subject retrieval proxies, not agent correctness or billing measurements.
The engine includes the owner's pre-existing uncommitted delegation work; each
raw report records the engine revision, dirty flag and Python source digest.

## Measurements

| Engine | File recall | Token precision | Mean packet |
| --- | ---: | ---: | ---: |
| T00 baseline | 16.3934% | 18.8629% | 1013.175 |
| T10 mechanical patches | 16.3934% | 18.8629% | 1013.175 |
| Initial selector (rejected) | 14.7541% | 11.6889% | 1071.975 |
| Matched excerpts (rejected) | 16.3934% | 15.9708% | 916.250 |
| Two candidate limit (rejected) | 14.7541% | 18.0650% | 769.375 |
| Compact source, before final tightening | 14.7541% | 20.0339% | 675.375 |
| Final selector and rendering | 14.7541% | 20.0339% | 624.725 |

The final replay passes the owner-adjusted precision gate, recall tolerance
(1.6393 percentage points below baseline) and packet-size requirement. Full offline suite, Ruff, strict package mypy and final focused checks pass. The source/hunk coverage proxy fell from 24/302 to 13/302. Smaller
excerpts leave more code for explicit recovery; this is a material limitation,
not proof that agents solve more tasks.

## Formatting and default budget

The same-content format audit renders one packet through the frozen T10 renderer
and the new renderer, then asserts identical parsed source blocks and delivered
line sets. On ten fixed requests: 37,803 legacy characters versus 32,762 compact
characters, a 13.3349% reduction. This excludes candidate-selection savings.
Caller text lists names and exact locations; the JSON packet keeps full caller
identities, confidence and source snippets. Literal occurrence lines retain
numbering. Excerpts number their first line and each segment, marking omitted
lines explicitly; session memory uses actual source ranges.

Before final tightening, the adaptive audit averaged 720.8 estimated tokens
versus 877.7 for an explicit 2,000-token budget. The sufficient rate was unchanged compared with that selector’s fixed budget
at 2/10 (T00 was 3/10); non-test requests contained zero test-source characters and no test
callers. The final adaptive audit averages 681.9 estimated tokens, with the same 2/10
sufficient rate and zero test-source/test-caller share on non-test requests.

## Live formatting smoke check

[Raw events](phase1-format-pilot/events.jsonl) and
[result](phase1-format-pilot/result.json) record one gpt-6-luna Codex CLI run using
the existing ChatGPT login. API credentials were removed and ChatGPT login was
forced. The sandbox was limited to an isolated fixture. The first invocation
failed argument validation before inference; the corrected invocation completed
in 33.86 seconds and passed three independent checks of the resulting edit.

The model received segment-only line numbering. This is a T14 formatting smoke
check, not a native-hook/MCP arm of T41 and not evidence of campaign savings.
Native reported usage: input 100,983, cached input 85,760, output 536, reasoning
output 82. Subscription usage is not an API invoice.

## Reproduction

```
python -m tests.benchmarks.replay_precision --ref 9f74f92151d655f308de08b165aa0fc6a239a983 --commits 40 --history 150
python -m tests.benchmarks.packet_audit --ref 9f74f92151d655f308de08b165aa0fc6a239a983 --adaptive
python -m tests.benchmarks.format_audit --ref 9f74f92151d655f308de08b165aa0fc6a239a983 --output output/benchmarks/format-audit.json
```

Use isolated temporary Git worktrees and config as the harnesses do. Never scan
or enable the user's live checkout as part of this measurement.

Final replay elapsed: 321.28 seconds. Engine Python SHA-256: `25b0030bfd8062632c831331d2fdc4dfbaa7581b8ea0ca4b573c536df9560648`.

Manual standing-context check: Claude Code 2.1.296 `/context`, MCP disabled,
no session persistence: project CLAUDE.md 2.3k tokens, total memory 2.4k; no
startup length warning. The optional estimator scale remains 1.0 as requested.

The independent production-source caller oracle finds six call sites across
build_task and render_task and loses none; the small fixture oracle also passes.
A multi-target fixture verifies a shared three-inferred-caller cap and resolved
callers first. This final counter adjustment follows the replay; its focused
check passes, and replay/audit packets exposed at most one/zero inferred callers.
The persisted edge-resolution form T16b remains a separate later task.
