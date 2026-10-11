# Retrieval reliability after the fresh Plexus campaign

This revision addresses observed extra discovery work. It does not replace or
rewrite the fresh campaign's measured agent usage. Its nine-case diagnostic
measures retrieval quality, not end-to-end tokens or dollars.

## Plan and evidence

The fresh campaign found a wrong GitHub edit target presented with high confidence,
severity requests suppressed by low-confidence prompt retrieval, and failed CLI
calls with options before the command. Efficient control agents already performed
targeted searches; forcing them to read every file would inflate the saving.

The implementation follows selective context delivery: pick the requested operation,
return affordable complete code, retain its relationships, and disclose missing
source. [Aider's repository-map documentation](https://aider.chat/docs/repomap.html)
describes selecting relevant symbols and dependency information within a budget.
[Serena](https://github.com/oraios/serena) provides a complementary example of
symbol-oriented inspection. This revision independently implements ranking and CLI reliability improvements.

## Implemented changes

1. Imperative requests use their leading operation as a ranking prior. Later
   constraints remain searchable and literal evidence is preserved. Short ambiguous
   introductions fall back to the full request; URLs and qualified names stay intact.
2. Extraction/parsing, sorting/ranking, detection and masking aliases improve
   operation matching. Symbol-name evidence carries more weight than repeated body
   vocabulary. A symbol's term coverage is counted once rather than rewarded on
   every repeated line.
3. Matching lines are grouped into symbols before selection. A helper cannot be
   excluded simply because eight stronger caller lines appeared in the same file.
4. Large enclosing classes do not displace affordable whole methods. Existing
   complete-source fitting and exact missing-range follow-ups remain budget bounded.
5. Confidence is based on delivered blocks rather than all matches in their file.
   An exhaustive `ValueError` identifier list does not alone establish edit readiness;
   a high score margin does not alone establish high confidence. A wholly absent
   leading topic remains low confidence despite acceptance-criterion matches.
6. Both `prism task ... --root ... --session ...` and
   `prism --root ... --session ... task ...` work. Command options override defaults,
   and defaults are cleared at command exit. Tests caught and corrected a Typer
   context-routing incompatibility before completion.
7. Managed integration instructions and the shipped context skill tell agents to
   use already supplied prompt context without fetching it again.
   Existing integrations receive these revised instructions when reinstalled.

## Frozen retrieval diagnostic

`tests/benchmarks/retrieval_economics.py` uses the same indexed Plexus checkout,
three original task families, and three phrasings per family. The expected targets
were frozen before these changes. Each packet has a 1,169 estimated-token budget,
leaving room for the normal 1,200-token prompt hook's header. Full JSON reports are
saved in this directory; estimates include packet serialization.

| Metric | Before | After |
|---|---:|---:|
| Expected target returned first | 2/9 | 8/9 |
| Complete expected target delivered | 2/9 | 8/9 |

The remaining privacy paraphrase requests both detection and masking. Masking is
returned first and detection is partial. Its frozen gold target is detection, so
the failure stays in the report even though the first returned method is relevant.
Privacy packets also disclose partial supporting definitions and do not claim
`sufficient=true`. A complete primary method does not imply all dependencies fit.

These are small, development-facing diagnostic cases, not an independent held-out
evaluation. They establish that specific retrieval failures improved; they cannot
establish a population-wide saving. A subsequent fresh agent comparison must use
the final implementation, equivalent tasks, quality checks, and actual recorded
usage, with cached and uncached inputs reported separately.

A supplemental severity paraphrase omitted the explicit rank table and aliases:
"Fix the final finding aggregation order when severity labels contain whitespace,
mixed case, or code-review aliases. Normalize string labels and preserve
severity-first then descending-confidence ordering." It selected a review schema
with low confidence, so the hook correctly supplied nothing. This is an additional
retrieval miss outside the frozen nine cases, and demonstrates continuing wording
sensitivity. It is not included in the 8/9 score. Three-word prompts without code
identifiers are also intentionally filtered by the existing prompt-hook chat gate;
they remain usable through the CLI.

## Validation

Generic regression fixtures cover repeated caller lines versus a short parser,
absent-topic confidence, URL and qualified-name preservation, operation focus,
global CLI root/session routing, command-option precedence and session reuse.
The full suite also exercises consent, freshness, budgets, prompt hooks, literal
completeness, exact ranges and previously supported retrieval cases.

Final verification on this working tree:

- `python -m pytest`: **346 passed** in 154.59 seconds.
- `python -m ruff check prism tests`: passed.
- `python -m ruff format --check prism tests`: 169 files formatted.
- `python -m mypy prism`: no issues in 119 source files.
- `git diff --check`: passed.
- Actual subprocess CLI on indexed Plexus, global options before `task`: returned
  `_severity_rank`; a second call using command-level options reused the same
  session and marked that primary source as already seen. The packets were 836 and
  934 estimated tokens respectively: additional supporting source filled the repeat
  packet, so session reuse alone does not guarantee a smaller entire response.
- Actual subprocess prompt hook with JSON host payload, original severity
  specification and a fresh session: exit 0, helper source supplied, **883 estimated
  tokens including the hook header**, below its 1,200-token cap.

The nine diagnostic packets total 10,140 estimated tokens before and 9,492 after,
while retrieving more complete intended targets. These local packet estimates
exclude agent histories, reasoning, edits and tests; they are not measured API
token savings. The previous campaign's end-to-end measurements remain unchanged.
