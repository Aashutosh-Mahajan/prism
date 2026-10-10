# ADR 0004 — Optional filtering of noisy command output

Status: accepted, built as a wrapper command · 2026-10-10 (update.md item 3.2)

## Context

After retrieval, a large share of an agent session's tokens is the output of its own commands:
test runs, builds, `git log` and `git diff`. Other tools (RTK-style filters) report 60–90% savings
on these outputs. PRISM does nothing here today.

Filtering changes what the agent sees, so a bug could hide a failure. CLAUDE.md §4.9 says PRISM
never modifies user source code and must be safe by default; §4.10 says everything is opt-in.

## Decision

- Ship it as an explicit command, `prism filter -- <command>`, **not** as a hook that rewrites the
  agent's commands. Claude Code's way of rewriting a Bash command (`updatedInput` on a
  `PreToolUse` hook) is documented to be combined with `permissionDecision: "allow"`, which skips
  the permission prompt; a hook that silently auto-approves rewritten commands would change the
  user's safety model, so PRISM does not do it. An agent (or the user) opts in by running tests and
  builds through the wrapper.
- It runs only when PRISM is enabled for this user in this repo; otherwise the command's output is
  printed unchanged.
- Output shorter than 60 lines is printed unchanged. Families (pytest, jest/vitest/mocha, flutter,
  go, cargo, npm/yarn install and build, git) remove only their own progress lines. Any line that
  looks like a failure, and 3 lines around it, is always kept; pytest keeps its whole FAILURES,
  ERRORS and short-summary sections. Unrecognised output that is still very long keeps its head,
  its tail and its failure lines. `git diff`, `show` and `log` are never cut in the middle.
- The full, unmodified output is written to `.aicontext/cache/tee/` (newest 40 kept) and its path
  is printed last. The exit status is the command's own.

## Consequences

- Fewer tokens per tool result, measured as a separate benchmark metric (tool-output tokens).
- A new class of risk (hidden failure lines) that is bounded by the tee file and the golden tests.
- The benchmark reports results with and without the filter so its share is visible.
