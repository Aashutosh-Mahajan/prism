## 8. Navigator & MCP Server — Targeted Retrieval (the core value)

### 8.1 Query operations

| Command | MCP tool | Purpose |
|---|---|---|
| `prism task "<request>" [--budget N] [--session ID]` | `prism_task` | **The primary retrieval call** (Section 8.5): for a request, symbol or file, the matching code, every exact occurrence of the strings/names/quantities it mentions, call sites, tests and impact, with a confidence. |
| `prism brief [--full]` | `prism_brief` | Print the **compact** session brief + freshness line (Section 9.3); `--full` prints all of `AGENTS.md`. Used by the SessionStart hook. |
| `prism locate <name>` | `prism_locate` | Resolve a symbol/file name (exact → qualified suffix → fuzzy). Returns candidates with file:lines. Ambiguity → ranked list, never a silent guess. |
| `prism context <target> [--budget N] [--depth D] [--with-source]` | `prism_context` | Build a context pack for a symbol, file, `file:line`, or route (`GET /orders`). Default budget 2,000 tokens. |
| `prism impact <target>` | `prism_impact` | Blast radius: what could break if this changes, plus tests to run. |
| `prism search "<text>"` | `prism_search` | Free-text search over symbol names, qualified IDs, docstrings, paths, comments, routes. BM25 locally (Phase 2); optional local embeddings (Phase 5, `prism-ctx[semantic]`, offline model). |
| `prism module <name>` | `prism_module` | Module summary from `.aicontext/modules/`. |
| `prism status` | `prism_status` | Index freshness, changed files, drift score, stale sections, last audit. |
| `prism recall ["<topic>"]` | `prism_recall` | Earlier sessions from the local work log (Section 9.4): what was asked, edited and noted. |
| `prism note "<text>"` | `prism_note` | Leave a one-line handoff note for the next session. |

### 8.2 Context pack assembly rules

1. Always include the target's exact location and signature.
2. Rank candidates (callers, callees, tests, co-changed, config/model touch-points) by: edge proximity × PageRank × co-change strength × recency.
3. Greedily fill the token budget; each item carries `why` so the agent can skip what's irrelevant.
4. `--with-source` inlines only the target's body (never whole files) when it fits the budget.
5. Include open audit findings and risk reasons for the target.
6. Output is stable and compact; Markdown by default, `--json` for tools.

### 8.3 Performance targets

- `prism locate` / `prism context` / MCP calls: **< 200 ms** p95 on a 100k-LOC repo (use the SQLite cache in `.aicontext/cache/`, rebuilt from the JSON artifacts if missing).
- Context pack default ≤ 2,000 tokens; brief ≤ 600 tokens.

### 8.4 MCP server (`prism mcp`)

The MCP server lets the host agent call PRISM as native tools instead of shelling out to the CLI and parsing text.

- **Transport:** stdio, local only, started by the host agent from the `.mcp.json` (or equivalent) entry that `prism init` adds with user consent. No network listener.
- **Implementation:** official MCP Python SDK in `prism/mcp/server.py`. Each tool is a thin wrapper over the same library function the CLI calls. No logic lives in the server.
- **Why it exists alongside the CLI:** structured JSON results (fewer parsing mistakes), tools are visible in the agent's tool list (more reliable use than remembered commands), the index stays loaded in memory (fast, < 200 ms), and it works for agents that can use MCP but have no shell.
- **Consent-aware:** on start it checks the per-user enable flag (Section 12.1). If PRISM is not enabled for this user or is paused, it exposes only `prism_status`, which reports that state.
- **Lean by default:** most agents send every tool's schema to the model on every turn, so `prism mcp` exposes only `prism_status`, `prism_task`, `prism_context` and `prism_impact` unless `--profile full` (or `PRISM_MCP_PROFILE=full`) is chosen. `prism_task` also resolves names and free text, which is what `prism_search`/`prism_locate` are for.
- **Read-mostly:** only `prism_audit_record`, `prism_audit_update`, and `prism_refresh_commit` write, and only inside `.aicontext/`, through the writer layer. No tool edits source code or runs shell commands.
- **Errors:** return structured errors (`not_enabled`, `index_missing`, `ambiguous_target` with candidates, `not_found` with suggestions, `budget_exceeded`) instead of raising, so the agent can recover.

| Tool | Input | Returns |
|---|---|---|
| `prism_status` | — | enable state, freshness, changed files, drift, stale sections, audit summary |
| `prism_task` | `query`, `budget?`, `repeat?` | request-level answer (Section 8.5) |
| `prism_brief` | `full?` | compact brief (or AGENTS.md) + freshness line |
| `prism_search` | `query`, `limit?` | ranked hits (id, kind, file, lines, score, snippet) |
| `prism_locate` | `name` | candidates (id, kind, file, lines, signature) |
| `prism_context` | `target`, `budget?`, `depth?`, `with_source?` | context pack (Section 7.1) |
| `prism_impact` | `target` | dependents by distance, tests to run, risk |
| `prism_module` | `name` | module summary |
| `prism_refresh_prepare` | `sections?` | refresh packet per stale section |
| `prism_refresh_commit` | `section`, `text` | validation result; resets drift on success |
| `prism_audit_plan` | `scope?`, `since?`, `depth?` | audit plan (Section 10.2) |
| `prism_audit_record` | `finding` | assigned ID, dedupe result, or validation errors |
| `prism_audit_update` | `id`, `status` | updated finding |
| `prism_audit_report` | — | report path + summary counts |
| `prism_graph_view_url` | `focus?`, `depth?` | local viewer URL (starts the viewer if the user allowed it) |
| `prism_recall` | `query?`, `limit?` | earlier sessions: requests, edited files/symbols, notes |
| `prism_note` | `text`, `session?` | records a handoff note in the local work log |

### 8.5 Request retrieval (`prism task`)

Benchmarks of real agents showed that retrieval the agent has to *remember to call* and then *double-check with grep* adds turns instead of removing them, and that every turn re-sends the whole context. `prism task` is therefore designed to be a complete answer to "where does this change belong", so an agent has no reason to search again:

1. **Literals.** Quoted strings, code-like names, numbers with units and multi-word phrases in the request are found *exhaustively* in the indexed source (via the persistent postings, never a repository scan) and listed as `file:line` + line. A list marked exhaustive covers every occurrence. Names the request uses that do not exist are reported as new. When a request gives an old and a new value, only the old one is searched.
2. **Blocks.** Candidate files are scored line by line; matches become a whole small symbol or a window, never a module header or a whole large class. Imports, headers, tests, docs and migrations are down-weighted; blocks connected in the call graph reinforce each other; related words (a small deterministic synonym table) count at half weight.
3. **Graph.** Callers of the leading symbols with the calling line, tests that mention them, and an impact count.
4. **Honesty.** `confidence` (exact evidence, margin over the next block, weighted coverage), `sufficient`, and a `Next:` line. Low confidence says to grep. An exhaustive literal list covers the searched text only; it never claims a behaviour is implemented.
5. **Budget.** The whole packet, JSON and text, stays within the budget (default 2,000; the prompt hook uses 1,200). Code already returned in a session is returned as a reference (`--session`, MCP server memory).

Every navigator query first compares the working tree with the manifest and, for an enabled user, updates just the changed files (Section 9.1), so an unannounced edit is still seen.

