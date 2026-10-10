# Retrieval revision after the Plexus pilot

This revision targets the observed failure: PRISM retrieval was added before
ordinary exploration instead of replacing it. The two-agent Plexus pilot used
more tokens overall with PRISM; its results have not been changed. No live-agent
rerun has been conducted for this revision. The current local working tree is
not a published release.

## Research and what was adopted

| Primary source inspected | Useful design | Application in PRISM |
|---|---|---|
| [Aider repository maps](https://aider.chat/docs/repomap.html), [implementation](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py) | Ranked signatures and dependency information inside a small map budget | Query-focused architecture maps with directory diversity, entry points, signatures and static relationships |
| [Serena symbolic tools](https://github.com/oraios/serena/blob/main/src/serena/tools/symbol_tools.py) | Inspect structure separately from selected symbol bodies; scope retrieval to a known file | Explicit overview/code modes, file outlines, file-qualified symbols and exact source ranges |
| [Context Mode](https://github.com/mksglu/context-mode) | Independent retrieval channels, reciprocal-rank fusion, relevant windows and session reuse | Body/symbol RRF with one vote per file per channel; exact missing-source windows |
| [RTK output filtering](https://github.com/rtk-ai/rtk#how-it-works) | Group and deduplicate output before it reaches the model; output reduction is distinct from bill reduction | Session range subtraction retained; concise maps instead of raw file listings; no unmeasured bill-saving claim |
| [Serena's Codex evaluation](https://github.com/oraios/serena/blob/main/docs/04-evaluation/030_results/020_codex_on_jbplugin.md) | Symbolic tools can help structural tasks yet cost more for simple substitutions | Instructions allow already-located small edits without broad orientation |

These are architectural ideas, not a claim that upstream tools demonstrate a
particular end-to-end saving for PRISM. The Aider/Serena/Context
Mode/RTK ideas were independently implemented; their code was not copied and
their libraries are not dependencies. In particular, Serena's GPL implementation
was inspected for behavior, not vendored into PRISM.

The designs were selected from implementation and official documentation, not
social-media compression claims. PRISM keeps source verbatim; it does not remove
comments or rewrite implementation code into lossy summaries to improve a counter.
There is no compulsory tool-routing gate or artificial whole-repository baseline.

## Changes

### One compact map for broad orientation

`prism task "repository architecture"` now selects overview mode automatically.
`--mode overview` makes the choice explicit; a file path returns that file's
symbol outline. Maps contain indexed counts, languages, selected external
imports, entry points, signatures and static import/call links. Files are chosen
with directory diversity rather than spending every row on one central package.
Scope terms focus maps on a subsystem. All rows, omitted markers and next-step
guidance share the same output budget. Maps are selective, do not contain bodies,
and set `sufficient` false: they are not an editing proof.

The session brief remains compact; a large global map is not injected into every
coding session. Only an actual architecture request asks for it. The existing
`prism_task` MCP tool handles both modes; no extra always-advertised tool was added.

### Self-contained source where it fits

Edit packets favor a complete primary body over peripheral excerpts. The fixed
45% primary-share cap was increased while preserving the overall packet cap.
Two matching methods in a small class can be delivered together. Exact symbol
lookups remain narrow. Used Python constants, imports and local helper definitions
are selected from a hash-verified AST rather than copying the file's header.
Unrelated top-level definitions are omitted. Other-language local dependency
support is not yet implemented; existing parsers still provide their symbols.

### Exact follow-ups and honest completeness

`file::Class.method` resolves within that file, `file:line` selects its containing
symbol, and `file:start-end` returns that specific range. Reversed/invalid ranges
and ambiguous names produce user errors. Partial packets list precise `read_next`
locations; the agent need not read the whole file to recover missing source.
Session memory stores actual delivered intervals, subtracts overlap, and drops
references when source hashes change. Source returned by `prism context
--with-source` now also uses hash verification.

Literal searches track whether file/work caps or unavailable source prevented a
complete candidate scan. Capped totals are lower bounds and incomplete scans never
claim exhaustive coverage. Long matching lines are no longer silently skipped.
The fallback is a targeted search, not suppressed evidence or false certainty.
Static relationships remain static; framework dispatch can still be missed.

### Stable fusion and lean workflow

Body BM25 and symbol metadata rankings now use reciprocal-rank fusion. Repeated
symbols in the same file cannot accumulate arbitrary metadata votes. Graph
expansion remains bounded and below source evidence. CLI, MCP, hooks and skills
use the same task assembler. Hooks reserve their own header inside the budget
and do not remember source when their answer is suppressed or abandoned.

Instructions ask for the actual user request once, then direct use of returned
evidence. They permit normal tools on weak matches, and no broad orientation
for an already-known small edit. Existing installed integration files are not
silently rewritten; reinstall/update integration through the existing lifecycle
when you want the new managed instructions in a different repository.

## Validation and limits

Regression cases cover maps at 128–2,000 estimated tokens, scoped symbol/range
reads, shared constants, cooperating methods, larger-budget continuation without
duplicate source, long matching lines and capped searches. Existing retrieval,
hook, navigator and skill checks are also exercised. A pre-existing compatibility
issue in skill introspection was fixed: Typer >=0.26 vendors Click, so validation
uses Typer's own group class while retaining command/flag checks.
[Typer's explanation](https://github.com/fastapi/typer#click-code).

Final local validation (Windows, Python 3.13): **334/334 full-suite tests passed**,
Lint, format and strict mypy passed.
The wheel built successfully, included upstream license/NOTICE files, and its
retrieval source files were byte-compared with the final working tree. The first
full run had one golden-file failure caused solely by CRLF versus LF; normalized
contents matched exactly. Golden snapshots and checkout attributes now use LF.
No golden semantic content was changed to obtain a passing result.
[Validation record](retrieval-validation-2026-10-07.json).

The bundled 14-query evaluation continues to locate 13/14 queries, including all
12 core cases. The existing stretch query "how long is a verification code good
for" still misses its labeled location. This is retrieval-only validation,
not successful edit evidence. The final mean answer is about 1,042
chars/4-estimated tokens, compared with about 888 in the earlier saved evaluation:
some packets are larger because they include actual support definitions and
missing-context guidance. That tradeoff is disclosed; fewer follow-up reads and
lower total cost remain hypotheses for the next live-agent benchmark.

Budgets use the documented chars/4 approximation and cover rendered text and
pretty JSON. They are not exact tokenizer guarantees; host transport/system
prompts remain outside PRISM's output budget. No new percentage saving is claimed.

## Next live comparison

Freeze this code revision and Plexus snapshot. Use identical tasks, models and
permissions; normal-tools control is not forced to dump source. Measure indexing
time/API tokens separately, then actual input/output/cache usage from transcripts.
Prefer a fresh session per task with the compact brief; do not add a broad
orientation phase to a small edit unless that phase is itself the task being
evaluated. A separate explicit orientation task can exercise overview mode.

Score both edits against the same independently checked fixtures. Preserve
failures, tools the agent ignores, full outputs, reruns and corrections. Record
the CLI versus prompt-hook transport, source/context actually shown, fallback
reads, latency and at least repeated pairs. The earlier Plexus report and scorer
are untouched. A favorable result is earned by correct work at lower full-session
cost, not by prettier graphs or a larger corpus/context ratio.
