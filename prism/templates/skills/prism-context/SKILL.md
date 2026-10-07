---
name: prism-context
description: Use at the start of any coding task in this repo, and for "where is / what calls / what breaks if" questions. Ask PRISM for the code instead of scanning or grepping the codebase.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Navigation

## Purpose

This repo has a local code index. One call returns the code a task needs, so you do not list directories, grep, or read whole files to get oriented.

## When to use

- At the start of any coding task: fix, feature, refactor, or a question about the code.
- Before you grep or open files just to find where something lives.

## Preconditions

None to check first. Call `prism task`; if it reports that PRISM is not enabled, not initialized, or not installed, work normally and do not nag. The index refreshes itself before each answer.

## Procedure

1. `prism task "<the request>"` (MCP: `prism_task`). Pass the user's wording, a symbol name, or a file path. It returns the matching code with line numbers, every exact occurrence of the strings, names and quantities in the request, call sites with their calling line, tests to run, and impact.
2. Edit from what it returned. A literal list marked exhaustive covers the whole indexed source: do not grep for those strings. Read more only where the answer says it is an excerpt or its confidence is low.
3. For a follow-up on one symbol: `prism context <symbol>` or `prism impact <symbol>` (MCP: `prism_context`, `prism_impact`). Run `prism impact` before changing a public signature, and update every caller it lists.
4. Run the tests the answer names. Hooks update the index after edits; without hooks, `prism update <files>` forces it.

## Outputs

- The requested change, made after reading only what PRISM pointed to, with the named tests run.

## Guardrails

- Never run `prism init`, `prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks in this conversation.
- Static analysis misses dynamic calls (reflection, string dispatch, framework magic): when the answer looks incomplete, do a targeted grep for that name, not a full scan.
- Never load `.aicontext/*.json` files into context and never edit `.aicontext/` by hand.
- If findings are listed as open, mention them; mark one fixed (`prism audit update <id> --status fixed`) only after its evidence command passes.
