---
name: prism-decisions
description: Use when the user makes or asks you to record an architecture or design decision ("let's go with X because Y", "write that down", "record this decision"), or when you need to know why the code is built a certain way. Reads and records ADR-style notes in .aicontext/decisions/.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Decision Memory

## Purpose

Decisions explain *why* the code is the way it is. PRISM keeps them as short, dated notes in `.aicontext/decisions/` so a future session can find the reason instead of re-arguing it. `prism search` indexes them.

## When to use

- The user settles a design question in conversation and wants it remembered.
- The user asks you to record, update, or supersede a decision.
- Before changing something that looks deliberate: check whether a decision explains it.

## Preconditions

1. `prism status` (MCP: `prism_status`) shows PRISM **enabled**. If not, don't record anything and don't enable PRISM yourself; tell the user.
2. Record a decision only when the user made it or explicitly asked you to record it. Never invent decisions from your own guesses about the code.

## Procedure

1. **Check what exists.** `prism decision list` (MCP: `prism_decisions`), or `prism search "<topic>"` to find related decisions. Read the relevant one with `prism decision show <id>`.
2. **Write it down.** `prism decision add --title "<decision in one line>" --context "<problem and forces>" --decision "<what and why>" [--consequences "<trade-offs, follow-ups>"] [--symbol <id>] [--supersedes <id>]` (MCP: `prism_decision_record`).
   - Title states the choice, e.g. "Store money as integer cents".
   - Context: the problem, constraints, and alternatives considered, in 1–4 sentences.
   - Decision: what was chosen and the main reason.
   - Consequences: what this makes easier or harder; follow-up work.
   - Use `--supersedes` when a new decision replaces an old one; PRISM marks the old one superseded.
3. **Confirm** to the user in one sentence, with the decision id.

## Outputs

- A new `.aicontext/decisions/NNNN-<slug>.md` note, searchable with `prism search`.

## Guardrails

- Keep each decision under ~600 tokens: it's a note, not a design doc.
- Only facts from the conversation or verified in code. No speculation.
- Never edit decision files by hand, and never delete them; supersede instead.
- Never run `prism init`, `prism scan`, or `prism enable` unless the user asks.
