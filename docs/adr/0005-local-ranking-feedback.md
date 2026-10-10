# ADR 0005 — Local ranking feedback from edits

Status: accepted, built · 2026-10-10 (update.md item 4.3)

## Context

When a request is vague, the first candidates are chosen from text and graph signals only. In a
repo the same areas are edited again and again, and the post-edit hook already learns which files
an agent changed. Using that is a cheap way to rank the likely site first.

CLAUDE.md §4.3 requires a deterministic index: the same code must produce the same
`.aicontext/` files. §3 forbids any model call.

## Decision

- Keep a small boost table in `.aicontext/cache/ranking_feedback.json` (gitignored, a disposable
  cache, **not** an index artifact): per file and symbol, a count of edits with a half-life of 30
  days, capped so feedback can reorder close candidates but never outrank an exact name match.
- Only the post-edit hook writes it; only `prism task` block scoring reads it.
- `ranking_feedback = false` in `prism.toml` (or `PRISM_FEEDBACK=0`) disables reading and writing,
  and the old ranking is then reproduced exactly.
- Nothing leaves the machine; nothing is shared through git.

## Consequences

- Answers for the same request can differ between machines (the feedback is per user). The index
  and its golden files are unaffected.
- Tests: replay a work log on a fixture and assert the boosted file ranks first; assert disabling
  restores the previous order byte for byte; assert an exact name match is never outranked.
