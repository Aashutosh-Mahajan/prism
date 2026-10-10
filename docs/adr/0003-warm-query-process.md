# ADR 0003 — Warm local query process

Status: accepted, built · 2026-10-10 (update.md item 1.4)

## Context

A warm `prism task` takes about 1.1–1.3 s on a 560-file repository: about 0.5 s is Python start-up
and imports, 0.3 s the working-tree check, 0.3 s literal tokenizing. The MCP server avoids the
start-up because it stays resident, so agents using the CLI wait longer than agents using MCP, and
a slow tool pushes agents toward `grep`. The goal is a p95 under 200 ms.

CLAUDE.md §4 forbids background activity in repos the user has not chosen and §8.4 forbids a
network listener.

## Decision

- The CLI hands `prism task` to a resident process **only when PRISM is enabled and not paused for
  this user in this repo**. The first query starts it; it is never started by `init`, `scan`,
  `status`, hooks or any other command.
- Transport is local IPC only: a named pipe on Windows, a Unix socket elsewhere, both inside
  `.aicontext/cache/` with owner-only permissions. No TCP port is ever opened.
- The process holds the index, the SQLite connections and the session memory, and re-checks the
  working tree at most once per second per query (an edit hook forces an immediate check).
- It exits after 10 minutes without a query, on `prism pause`, `prism disable`,
  `prism uninstall-integration`, and when the repo's consent flag disappears.
- If it cannot be reached or started, the CLI answers in-process exactly as today. Output is
  byte-identical either way (covered by the surface parity tests).

## Consequences

- Warm CLI queries cost the same as MCP queries.
- One more process can exist while a repo is in use; it is visible in `prism status` and stoppable
  with `prism pause`.
- Consent tests must assert that no process is started in a repo that is not enabled, that
  `pause` stops it, and that it leaves nothing behind after `uninstall-integration --purge`.

## Alternatives rejected

- Keeping the CLI cold and only trimming imports: reaches about 0.7 s, not 200 ms.
- A system service started at login: violates the opt-in rule.
