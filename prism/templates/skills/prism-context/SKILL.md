---
name: prism-context
description: Locate unknown code and answer "where is / what calls / what breaks if" questions using the local PRISM index. Reuse supplied context; skip discovery for already-located edits.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Navigation

## Purpose

This repo has a local code index. Retrieve evidence for the actual request; avoid a separate broad orientation phase for an already-located edit.

## When to use

- To locate unknown code for a fix, feature, refactor, or question.
- Before you grep or open files just to find where something lives.

## Preconditions

No status call is needed first. Follow the repository's configured transport: native `prism_task` for MCP installs, `prism task` for CLI installs. Discover a deferred tool once if needed. If unavailable or disabled, use ordinary targeted tools; do not try an unverified alternate transport. Queries refresh the index.

## Procedure

1. Reuse context supplied with the prompt. For unknown code only, call the configured task tool with the user's actual wording once. Architecture requests return a selective map; edits return source and related definitions. Explicit modes are `overview` and `code` (CLI: `--mode`; MCP: `mode`).
2. Use the evidence directly. Lists marked exhaustive cover the indexed matching lines; lists marked limited do not. For partial source, read only the `read_next` ranges or request that exact symbol with a larger budget. When `Next` says "Edit-ready" the listed sites are complete: edit them now and do not grep, `find`, `ls -R` or read whole files for what the packet already lists. Do not repeat retrieval with synonyms and then read whole files when the packet already answers the request. Weak matches still need a targeted ordinary search; never suppress missing evidence just to save tokens. A `Patch:` line is a checked patch for a mechanical change at the exhaustive sites: run the command it gives, then review `git diff` (PRISM never edits files itself; `prism diff "<request>"` writes the same patch). A `Twins:` line lists copies of the same function: change all of them. When the packet is not enough, `prism find "a" "b"` runs several searches in one call (`--glob`, `--regex`); `--detail brief` returns sites and tests only.
3. For an old-value replacement, `verify` mode lists remaining old-value matches. It does not verify arbitrary new behaviour; use the diff and relevant tests for that. Follow up with context or impact only when required evidence is missing, using tools exposed by the configured transport. Check affected callers before changing a public signature; static lists may be incomplete.
4. Run relevant tests. Hooks update the index after edits; queries also catch working-tree changes. Use `--session <id>` for repeated CLI retrieval so unchanged code becomes references. MCP maintains memory automatically; its `session` argument can share the host's session ID with CLI/hooks across reconnects. MCP task text is compact by default; request `format="json"` only when structured data is needed.
5. When you finish a multi-step task or stop with work left, leave one line for the next session: `prism note "<what changed; what is left>"`. Requests and edited files are logged automatically, so note only what the code cannot show. The next session starts with this summary; `prism recall "<topic>"` finds older ones.

## Outputs

- The requested change, made after reading only what PRISM pointed to, with the named tests run.

## Guardrails

- Never run `prism init`, `prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks in this conversation.
- Static analysis misses dynamic calls (reflection, string dispatch, framework magic): when the answer looks incomplete, do a targeted grep for that name, not a full scan.
- Never load `.aicontext/*.json` files into context and never edit `.aicontext/` by hand.
- If findings are listed as open, mention them; mark one fixed (`prism audit update <id> --status fixed`) only after its evidence command passes.
