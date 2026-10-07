# Persistent local context engine

Prism keeps the repository's knowledge on the user's machine. The host model receives a small
working set for the current request. A local knowledge database is not an expansion of the
remote model's context window; its benefit is avoiding repeated discovery and unnecessary reads.

## What is stored

`prism init` and `prism scan`, requested by the user, build portable facts under `.aicontext/`:
symbols, locations, calls/imports, tests, routes/models/configuration, health, history and module
facts. SQLite caches support body/symbol retrieval. Narrative sections remain optional and are
written by the user's own host agent, not an API call made by Prism. Source stays in the working
tree and is verified against the indexed hash before returning it.

`prism knowledge` inspects the local inventory within a budget. It is useful for checking what
was built; agents should not add it as a prerequisite to every edit.

## Task compilation

One request runs several local passes: discover candidates from source and symbol postings,
verify exact literals, rank edit units, identify object producers and small contracts where the
request explicitly describes an output shape, expand needed local definitions and graph links,
then fit source and recovery instructions to the shared budget. These passes do not call a model.

For example, an object-field request describing `(value / previous / kind)` prefers the builder
defining those keys over a display function merely reading them. Matching type/interface
declarations and small literal frontend construction candidates are retained. Python output
builders are AST-verified to distinguish returned dictionaries from logging dictionaries.
Construction matching is bounded and does not replace a typechecker. Unrelated tests are filtered from ordinary edit candidates; relevant
tests are still found through the target's graph, source mentions and package relations.
Backtick references to those existing fields are interpreted as shape context, avoiding a
repository-wide literal search for generic names. Quoted literal strings and ordinary rename
requests retain their exact matching behavior. Contracts without callers do not reduce the
builder's caller quota.

A scalar such as a class's lifetime setting is a standalone edit range, rather than the entire
class. Exact literal matches still disclose all matching indexed locations. The agent must decide
which occurrences belong to the user's behavior; an exhaustive match list is not a command to
change every occurrence of a common number.

The compiler prioritizes complete primary edit source. A partial packet reserves room for a
missing range rather than silently spending the whole budget on optional graph data. Sufficiency
describes supplied evidence; dynamic dispatch, runtime behavior and ambiguous requirements can
still need targeted investigation. Verification remains the host agent's responsibility.

## CLI and MCP use the same engine

```powershell
prism task "Every metric object (value / previous / kind) should include change_pct" --session work-42
prism knowledge --budget 600
```

Native MCP call:

```json
{"name":"prism_task","arguments":{"query":"Every metric object (value / previous / kind) should include change_pct","session":"work-42","budget":2000}}
```

The MCP tool's compact default matches CLI text. `format="json"` returns the structured packet
with a compatible text representation. A client should present one representation to the model,
not duplicate both. Existing structured clients need to opt into JSON when upgrading.

Keep the lean profile for coding: task, context, impact and status. The full profile adds
inspection, navigation, audit, refresh and decision tools on demand. Native registration is
installed through Prism's existing agent adapters with user consent; a custom client bridge is
not required by the product.

## Reuse and invalidation

- The existing prompt hook can deliver task evidence before the first model turn. When that
  packet answers the task, use it directly without a second task call.
  It starts with a 1,200-token estimate and can expand to the default 2,000-token hard cap
  only when the larger packet completes the evidence. Explicit lower caps remain respected.
  Discarded retrieval attempts never enter session memory.
- CLI and MCP accept the same explicit session ID. Hooks use their host's session ID. Pass the
  same value to reuse their delivered ranges, including after MCP reconnects.
- Only source actually delivered in the final response enters session memory. Removed/truncated
  ranges cannot hide source the agent has never received.
- Changed-file hashes invalidate those ranges. Unchanged files remain references. A new
  conversation needs a new session ID because disk memory does not imply model memory.
- Full packets without session state are cached locally (maximum 32). Their keys include query,
  budget, mode, cache format, source hashes/stat revisions and artifact versions. Direct library
  queries detect changed source before reusing a packet; CLI/MCP also refresh the index first.
  Cached delivered source is hash-verified even when timestamps are preserved. Configured external
  Graphify exports retain their own validation path and bypass full-packet caching.
- Local caches reduce computation and latency, not remote tokens by themselves. Fewer model
  calls, shorter evidence and session-aware responses are what reduce model input.

## Verification and limits

Tests cover budget bounds, delivery accounting, source invalidation, cross-surface session reuse,
native MCP output parity, producer ranking and scalar edits. Existing freshness, hooks, retrieval
and graph tests remain part of validation. Full-repository knowledge is supported by the existing
index and module artifacts; the added inspection command does not certify complete semantic
understanding of arbitrary code.

Packet token estimates use `ceil(characters/4)`. Provider usage records are required for actual
agent token comparisons. A small successful retrieval benchmark cannot establish a universal
percentage saving; measure edits and correctness in matched fresh sessions on varied tasks.

## This project's local context

The Prism checkout is enabled and indexed with generated fixtures, `tmp/`, `output/` and
benchmark runs excluded. Portable facts and graph relationships cover the indexed project
source; 21 purpose, architecture, convention and module narratives were refreshed through
the validated writer. Project-local Codex MCP and prompt hooks are installed. Host trust and
hook activation still determine whether context arrives automatically in a new session.

CLI is the shell interface for indexing, querying and hook delivery. MCP exposes the same
operations as persistent stdio tools for a host agent. Both retrieve a working set from local
knowledge; neither creates the remote model's attention/KV cache on disk. Core indexing and
retrieval use zero LLM tokens. Host-authored narratives and coding agents consume model tokens.

The latest [preflight pilot](token-saving-delivery-2026-10-08.md) measures actual edit-agent
usage for packets retrieved through each transport and supplied before the first turn.
This is distinct from tool-only retrieval and from a verified native-host hook run.
