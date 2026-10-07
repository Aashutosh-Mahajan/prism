# Token-saving delivery — 8 October 2026

The local Prism project context is built and enabled. The latest matched preflight pilot
reduced processed edit-agent input by **18.4% through CLI** and **20.5% through MCP**.
All arms passed **18/18** frozen and additional assertions. A huge general saving remains
unproven; this is a two-task, one-repetition descriptive pilot.

## Actual provider counters

| Across both edits | Without Prism | CLI preflight | MCP preflight |
|---|---:|---:|---:|
| Processed input | 510,290 | 416,415 | 405,800 |
| Cached input (included above) | 471,424 | 385,152 | 377,088 |
| Uncached input | 38,866 | 31,263 | 28,712 |
| Generated output | 4,377 | 4,713 | 4,335 |
| Input + output | 514,667 | 421,128 | 410,135 |
| Model turns | 13 | 12 | 11 |
| Cache-weighted input proxy | 86,008 | 69,778 | 66,421 |

Counters come from deduplicated provider usage records in every completed agent transcript.
Input includes cached tokens once. The proxy is uncached input + 0.1 × cached input,
a comparison measure rather than a monetary price. Output is reported separately.

## Per-task input

| Task | Without | CLI | MCP |
|---|---:|---:|---:|
| Code expiry | 229,880 | 207,286 (9.8% saved) | 169,738 (26.2% saved) |
| KPI field | 280,410 | 209,129 (25.4% saved) | 236,062 (15.8% saved) |

## What changed

- Local project indexing excludes test fixtures and generated benchmark folders. The checkout
  now contains 188 indexed source files, 1,531 symbols, 2,944 calls and 638 imports, with no
  parse errors and no stale narrative sections. Twenty-one narratives were refreshed through
  Prism’s validated writer; the whole agent brief remains under its 600-token estimate cap.
- Output-shape field references in backticks no longer cause noisy global literal searches.
  Quoted literal strings and ordinary rename requests retain exact matching.
- Prompt delivery starts small and expands within the default 2,000-token cap only when the
  larger packet completes evidence. Undelivered attempts do not enter session memory.
- Project-local MCP registration and session/prompt/edit hooks are installed. CLI and MCP
  share the same core; compact output, explicit session reuse and guarded local caches remain.
- A final refinement prevents contracts with no callers from halving the builder caller
  quota. It passed focused regression tests **after** the live pilot; its possible agent
  savings are not included in the table.

## Build cost and meaning of local context

Core indexing and retrieval make no model calls: **0 LLM tokens**. Building the four indexed
trial copies took 51.21 seconds total. Root scan timing was not isolated.
Host-authored narratives and this implementation work consume model tokens and are excluded
from the edit-agent comparison. The whole context-building effort is therefore not claimed free.
Disk knowledge is an index, source postings, relationships and narratives; it is not a remote
model context window or KV cache. Only request-specific evidence is sent to the agent.

## Design and practical limits

Six fresh agents received the same two real requests, verification instructions and frozen
original application sources, using inherited gpt-6.1-sol settings with no parent history.
Baseline used normal targeted discovery. CLI and MCP packets came from the actual transports
and were supplied in the first prompt; identical presentation-only Markdown fences/blank
lines were omitted from both treatments. One native MCP prism_task call prepared each packet.
Provider counters include those delivered packets and all agent edits/checks. Local transport
preparation has no LLM calls. Parent implementation, narration and orchestration are excluded.

This tests host preflight delivery, not a verified native Codex prompt-hook run or ordinary
tool-only retrieval. With an active prompt hook, the same evidence can arrive before the
first turn even when MCP is registered. The earlier tool-only pilot still showed CLI input
+13.8% and MCP -11.3%; those results remain in the earlier report. Preflight removes a
retrieval turn but does not force an agent to avoid redundant checks. Remaining traces still
contain source rereads, caller checks and dependency probes. Differences between CLI and
MCP preflight here include agent variance; both use identical retrieval content.

All frozen assertions plus zero-current, rounding, unchanged-value and frontend-type checks
passed. Agents also ran isolated production-function tests. Full Django/frontend validation
was unavailable in these copies; no dependencies were installed. No failures or sessions
were discarded, and no full-study statistical or universal savings claim is made.

The root CLI is enabled under the normal registry and doctor reports all checks green.
Native MCP smoke checks used an isolated root consent registry because this tool runtime
denied reading the default user registry. Enabled/fresh status and MCP-to-CLI session reuse
passed there. Installed configuration is verified; live host trust/hook activation is not.

## Validation and use

- Full offline suite: **361 passed** before the final caller-quota refinement.
- Final focused suite: **64 passed**, including the caller-quota regression.
- Ruff lint/format, strict mypy, artifact checks and whitespace checks passed.
- `prism knowledge --budget 600` inspects built knowledge.
- `prism task "<actual request>" --session <conversation-id>` retrieves an edit working set.
- MCP: `prism_task` with the same query/session; keep compact output and the lean profile.
- Review installed hooks in the host before relying on automatic preflight. Use supplied
  evidence once, then make the edit and run relevant checks. Larger packets, repeated broad
  orientation and exposing all MCP tools can undo the saving.

Next evidence needed for a large saving claim: varied tasks and repeated native-host trials,
including full builds and schema overhead. Preserve correctness and count unsuccessful runs.

Raw preregistration, source copies, packets, wire traces and all six transcripts:
`D:/Projects/prism/.benchmark-runs/preflight-2026-10-08/`.
Machine-readable counters: [JSON](token-saving-delivery-2026-10-08.json).
Architecture and usage: [context engine](context-engine.md).
