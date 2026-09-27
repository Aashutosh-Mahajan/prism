---
name: prism-refresh
description: Use when PRISM reports stale AGENTS.md or module-summary sections, after significant structural changes, or when the user asks to refresh the project brief. Rewrites only the narrative sections that drifted.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Narrative Refresh

## Purpose

PRISM keeps the factual parts of `.aicontext/AGENTS.md` and `.aicontext/modules/*.md` current on its own. The **narrative** parts (purpose, architecture, conventions, module explanations) are written by you, the host agent, and only when PRISM's drift score says the code changed meaningfully. This keeps the brief accurate without spending tokens on every edit.

## When to use

- `prism status` / the session brief reports stale sections. Offer this **after** finishing the user's current task, not in the middle of it.
- The user asks to refresh, update, or rewrite the project brief or a module summary.

## Preconditions

1. `prism status` (MCP: `prism_status`) shows PRISM **enabled**. If it isn't, stop and tell the user; don't enable it yourself.
2. If files changed since the last update, run `prism update` first so the refresh is based on current code.
3. If no sections are stale and the user didn't ask explicitly, stop and say the brief is up to date.

## Procedure

1. **Get the refresh packet.** `prism refresh prepare [--sections <names>]` (MCP: `prism_refresh_prepare`). For each stale section it gives:
   - the current text,
   - the structural diff since the section was last written (added/removed modules, public API changes, new routes/models/config, new dependencies),
   - context packs for the symbols involved,
   - the section's token limit.
2. **Read only what the packet points to.** Use `prism context <target>` for anything you need to understand better. Don't scan the repo.
3. **Rewrite each section.**
   - Keep what's still true, fix what the diff made wrong, add what's new. Don't reword correct text.
   - Stay under the section's token limit; the whole `AGENTS.md` must stay ≤ 600 tokens.
   - Write for an AI agent starting a fresh session: concrete names, file paths, commands, data flow, and gotchas. No marketing, filler, or history unless it prevents a likely mistake.
   - Include only facts you verified in code or the packet.
4. **Commit each section through PRISM.** Save the text to `.aicontext/cache/refresh/<section>.md` and run `prism refresh commit <section> --file <path>` (MCP: `prism_refresh_commit` with the text). PRISM checks markers and length and resets that section's drift. If it rejects the text, fix the reported problem and retry.
5. **Report** in one or two sentences which sections you refreshed and what changed materially.

### What each section should answer

| Section | Should answer |
|---|---|
| `purpose` | What the project does and for whom, in 2–3 sentences. |
| `architecture` | Main components, how a request/data flows through them, where state lives. |
| `conventions` | Patterns to follow (error handling, naming, layering, testing) and traps to avoid. |
| `modules/<name>` | What the module is responsible for, its key entry points, what depends on it, and what not to do in it. |

## Outputs

- Updated narrative regions in `.aicontext/AGENTS.md` and/or `.aicontext/modules/<name>.md`.
- Drift reset for each committed section.
- A short summary to the user.

## Guardrails

- Never edit `AGENTS.md` or module files directly, and never touch `<!-- prism:generated:* -->` regions. Write only through `prism refresh commit`.
- Never exceed token limits; shorter and correct beats longer.
- Don't guess. If you can't verify something, leave it out.
- Never run `prism init`, `prism scan`, or `prism enable` unless the user asks.
