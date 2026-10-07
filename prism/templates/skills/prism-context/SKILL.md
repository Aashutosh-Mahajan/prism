---
name: prism-context
description: Use at the start of any coding task in this repo, and for "where is / what calls / what breaks if" questions. Ask PRISM for the code instead of scanning or grepping the codebase.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Navigation

## Purpose

This repo has a local code index. Retrieve evidence for the actual request; avoid a separate broad orientation phase for an already-located edit.

## When to use

- To locate unknown code for a fix, feature, refactor, or question.
- Before you grep or open files just to find where something lives.

## Preconditions

None to check first. Call `prism task`; if it reports that PRISM is not enabled, not initialized, or not installed, work normally and do not nag. The index refreshes itself before each answer.

## Procedure

1. If PRISM already supplied context with the prompt, use that packet without another retrieval. Otherwise call `prism task "<the request>"` (MCP: `prism_task`). Pass the user's actual wording once, rather than a sequence of guessed searches. Architecture requests return a selective map of signatures and relationships; edit requests return source, used local definitions, call sites and test candidates. Explicit modes: `--mode overview` or `--mode code` (MCP: `mode`). A file path in overview mode returns its symbol outline.
2. Use the evidence directly. Lists marked exhaustive cover the indexed matching lines; lists marked limited do not. For partial source, read only the `read_next` ranges or request that exact symbol with a larger budget. Do not repeat retrieval with synonyms and then read whole files when the packet already answers the request. Weak matches still need a targeted ordinary search; never suppress missing evidence just to save tokens.
3. For a follow-up on one symbol: `prism context <symbol>` or `prism impact <symbol>` (MCP: `prism_context`, `prism_impact`). Run `prism impact` before changing a public signature, and update every caller it lists.
4. Run relevant tests. Hooks update the index after edits; queries also catch working-tree changes. Use `--session <id>` for repeated CLI retrieval so unchanged code becomes references. MCP maintains memory automatically; its `session` argument can share the host's session ID with CLI/hooks across reconnects. MCP task text is compact by default; request `format="json"` only when structured data is needed.

## Outputs

- The requested change, made after reading only what PRISM pointed to, with the named tests run.

## Guardrails

- Never run `prism init`, `prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks in this conversation.
- Static analysis misses dynamic calls (reflection, string dispatch, framework magic): when the answer looks incomplete, do a targeted grep for that name, not a full scan.
- Never load `.aicontext/*.json` files into context and never edit `.aicontext/` by hand.
- If findings are listed as open, mention them; mark one fixed (`prism audit update <id> --status fixed`) only after its evidence command passes.
