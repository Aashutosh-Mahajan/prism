# Prism improvement plan (10 October 2026)

Goal: a trustworthy, repeatable token saving (target 70%+ of total tokens on edit tasks, measured with confidence intervals), with CLI and MCP delivering the same result.

## A. Why CLI and MCP differ so much

Both call the same engine (`op_task`), so capability is identical. The gap in the data is delivery plus noise:

| Cause | Evidence / mechanism | Status |
|---|---|---|
| Single runs, no repetition | The winner flips: run 3 CLI −52% vs MCP −33%; run 4 CLI −1% vs MCP −37%; run 6 CLI+hook −37% vs MCP+hook −50%. A flip means noise, not a real gap. | Not controlled |
| Adoption differs | CLI relies on the agent remembering a shell command; one CLI session made zero Prism calls. MCP tools sit in the tool list. | Partly fixed by the hook |
| MCP schema cost per call | Even 4 lean tools add tokens to every model call (re-read each turn). | Open |
| Different "seen code" memory | CLI keeps it per `--session` on disk; MCP keeps it in server memory. Repeats are returned as references in one and as full code in the other when the session key is missing. | Open: unify |
| Different result framing | CLI prints text; MCP returns JSON plus one text copy. Different size and different habits (agents re-grep after one, trust the other). | Open: make byte-identical |
| Different freshness path | CLI query checks the tree each call (slow, about 1.3 s); MCP server keeps state warm. Agent behaviour changes with latency. | Open |
| Arm setup differs | MCP arm edits `mcp_config.json`; CLI arm needs PATH shim. Different prompts in early runs. | Fixed in v5/v6, same prompt |

## B. Plan

### Phase 1 — Make arms equal (days 1–3)
1. One delivery adapter: CLI, MCP and hooks all render the same packet bytes via one function; a parity test asserts equal packets for 30 queries.
2. Shared session store for "already sent" ranges (disk-backed, keyed by host session ID), used by MCP too.
3. Cut MCP overhead: one tool (`prism_task`) by default, terse description, schema under 150 tokens; measure per-call cost.
4. Warm daemon for CLI: `prism task` talks to a local resident process (stdio/socket, no network) so CLI latency matches MCP; target p95 under 200 ms.
5. Always-on hook for every host that supports one (Claude Code, Codex, Gemini CLI, Antigravity), so adoption does not depend on the agent.

### Phase 2 — Cut the real cost drivers (week 1–2)
6. Stop signal: a Stop/PostEdit hook runs `verify` and tells the agent "all sites done, tests listed, finish", ending the loop early.
7. Test selection: return the exact tests to run so the agent does not search for them.
8. Output filtering: trim noisy shell output (tests, git, builds), keeping failures and a tee file for detail.
9. Edit-ready packets: for change requests include the exact lines to modify plus a suggested diff-scope, so no re-reads.
10. Stable cacheable preamble: keep the injected header and instruction text byte-identical so provider prompt caching hits; put variable content last.
11. Tool-result clearing guidance: tell the host agent to drop stale packets (skill text), no Prism code changes.

### Phase 3 — Retrieval quality (week 2–3)
12. Semantic search on by default when the optional model is present; fall back to BM25.
13. Dart, Kotlin, Swift symbol parsing so call graphs exist for mobile code.
14. Learned ranking feedback: record which listed sites the agent actually edited, boost them next time (local, deterministic).
15. Latency: incremental text corpus, prebuilt postings, avoid re-reading manifests; target 200 ms.

### Phase 4 — Proof (week 3–4)
16. Benchmark kit run on Claude Code, Codex, Gemini CLI, Antigravity, each with baseline / CLI / MCP / hook.
17. 3 repositories × 8–10 tasks × 3 repetitions; report mean, median, 95% interval, and the CLI−MCP gap with a significance test.
18. Acceptance gate: CLI and MCP within 10 points of each other at p<0.05; average total-token saving 70% or the report says so honestly.
19. Cost view: add provider cost (cache read at 0.1×) next to token counts.

### Phase 5 — Product hygiene
20. `prism doctor` checks adoption (is the hook firing, is the rule loaded) and prints why an agent made no Prism calls.
21. Docs: one page "when Prism helps and when it does not" (small single-file tasks may not benefit).
22. Keep CI gates: ruff, mypy, full tests, reliability matrix, parity test, token-budget tests.

## C. Exit criteria
- CLI and MCP packets byte-equal; per-call MCP overhead under 150 tokens.
- Query p95 under 200 ms.
- Measured, repeated results on at least two hosts and three repositories.
- Honest report whether 70–75% is reached.
