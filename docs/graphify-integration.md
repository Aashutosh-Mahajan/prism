# Graphify-assisted retrieval

PRISM uses selected Graphify retrieval algorithms inside its own budgeted
`prism task` pipeline. This is a focused integration, not a Graphify dependency
or replacement for PRISM's index. No external service, API key, model, or new
MCP tool is needed for PRISM's retrieval.

## Available without installing Graphify

Requests to explain or trace an implementation can include a small connected
slice of the call graph, alongside the matching source. Graphify-derived seed
selection keeps different request terms represented; hub-aware traversal is
limited to two hops, 18 nodes and six neighbors per expansion. Low-confidence
call edges and test-only neighbors are excluded. Every source block is verified
against the current PRISM manifest before it is returned.

Ordinary edits, exact lookups and exhaustive literal matches keep their focused
path. Graph expansion shares the existing packet budget rather than adding a
second answer. Existing CLI, MCP and prompt-hook callers use the same library.

Session memory remembers only source lines actually delivered. Overlapping
reads return unseen portions; already shown ranges are referenced without
repeating source. CLI, hooks and MCP invalidate remembered ranges when the
corresponding file changes. Legacy session files without hashes are ignored.
Prompt hooks reserve room for their header inside the configured budget and
remember code only when a non-silent answer is actually returned. Very small
budgets that cannot fit both the header and a packet leave the hook silent.

## Optional: reuse an existing Graphify export

If you already have a Graphify graph for the same repository, add this setting
to an existing `prism.toml`:

```toml
graphify_graph = "graphify-out/graph.json"
```

Alternatively, add the key under `[tool.prism]` in `pyproject.toml`. The default
is unset: PRISM never generates or downloads a Graphify export automatically.
The file must resolve inside the repository, including after symlink resolution.

The adapter accepts node-link exports with `links` or `edges` and legacy
`_src`/`_tgt` endpoints. Only `EXTRACTED`/`INFERRED` edges guide discovery.
Exported nodes are ranked by label/rationale matches, term coverage and rarity.
Search postings are cached per export revision in an open MCP store. Discovery
is bounded to two hops and 40 nodes; at most six source hints enter the selector.

The export is advisory. Current PRISM symbols are resolved by name within an
indexed file rather than trusting exported line numbers. For a language without
a PRISM parser, a small location window can be returned only if the current
line contains the label's terms. Out-of-repository/unindexed files are excluded.
Documentation/rationale nodes can lead to code, but raw unindexed documents and
graph prose are not injected into answers.

Graph-led answers are labeled `graphify hint` and are not promoted to high
confidence by graph membership alone. Imported edges do not become verified
callers or impact counts. Regenerate Graphify exports after structural refactors:
source verification cannot certify an old export's relationship claims.

Limits: 16 MB of JSON, 50,000 nodes, 200,000 edges. Missing, malformed, oversized
or outside configured exports produce a user error when this retrieval path
is needed. Remove `graphify_graph` to use only native PRISM. No Graphify grammar
dependencies are installed, avoiding conflicting tree-sitter requirements.

## Manual validation

The initial integration was delivered without test runs at the user's request.
The subsequent retrieval revision adds regression validation; see
[retrieval research and changes](retrieval-research-2026-10-07.md). These are
manual reviewer checks, not measured agent savings. From the root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m prism task "explain how build_task works" --budget 1200 --session graph-review
.\.venv\Scripts\python.exe -m prism task "explain how build_task works" --budget 1200 --session graph-review
```

Compare the first and repeat answers; previously delivered code should become
references. Try a small budget followed by a larger one in a new session; the
second answer must include code the first could not deliver. In a disposable,
enabled repository, edit a returned file and query again with the same session:
changed code must be returned rather than an old reference. Check text and JSON
outputs against the requested chars/4 budget.

For the optional importer, configure a fresh Graphify export of that repository
and query code connected to a rationale/document node. Compare with the setting
removed. Check duplicate names, stale locations, outside paths and uncertain
edges: hints must not claim verified relationships or bypass source checks.

For end-to-end efficiency, compare normal tools, current PRISM and this version
on identical tasks/models with repeated fresh sessions. Include edit correctness,
all input/output and cached tokens, turns, time and preparation costs. Smaller
retrieved context alone does not prove lower total cost. No savings percentage
has been measured for this integration; expansion can add context on some tasks.

## Attribution

Upstream is pinned to `f765dcb3415d60fcfce390868da49e77894f2dc2`.
See [third-party notices](../THIRD_PARTY_NOTICES.md) for modifications and licenses.
