---
name: prism-context
description: Use at the start of any coding task in this repo, and whenever you need to find where code lives, what calls it, or what a change will affect. Query the PRISM index instead of scanning or grepping the codebase.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Navigation

## Purpose

This repo has a PRISM index in `.aicontext/` that already knows every symbol, file, call, import, test mapping, and risk score. Use it to load **only** the code the task needs, instead of exploring the repository to get oriented.

## When to use

- At the start of any coding task (fix, feature, refactor, explanation of code).
- Whenever you're about to list directories, grep, or open files just to find where something is.
- Before changing a public function, class, route, or model (to see what it affects).

## Preconditions

1. Run `prism status` (MCP: `prism_status`).
   - **enabled** → continue with this skill.
   - **not initialized / not enabled for you / paused / `prism` not installed** → work normally without PRISM. If `.aicontext/AGENTS.md` exists you may read it as background (it may be stale). Don't enable PRISM, don't nag the user.
2. If the status shows files changed since the last update and no hooks are installed, run `prism update` first.

## Procedure

| Step | CLI | MCP tool |
|---|---|---|
| 1. Get the project overview (skip if the session-start hook already injected it) | `prism brief` | `prism_brief` |
| 2a. Find code by description | `prism search "<words>"` | `prism_search` |
| 2b. Find code by name | `prism locate <name>` | `prism_locate` |
| 3. Get the context pack for the target | `prism context <target> [--budget 2000] [--with-source]` | `prism_context` |
| 4. Before editing a public symbol: see what it affects | `prism impact <target>` | `prism_impact` |
| 5. Understand a whole module (only if needed) | `prism module <name>` | `prism_module` |
| 6. After editing, if no hooks are installed | `prism update --files <changed files>` | — |
| Optional: show the user the graph around your change | `prism view --focus <target>` or `prism graph export --mermaid --around <target> --depth 1` | `prism_graph_view_url` |

`<target>` can be a qualified symbol (`pricing.discounts.apply_discount`), a file path, `file.py:123`, or a route (`"POST /orders"`).

**Working through a task:**

1. Search or locate the target. If several candidates match, choose by file path and signature; ask the user only if it's still ambiguous.
2. Get the context pack and read the `read_list` items in order, only at the given line ranges. Skip items whose `why` isn't relevant.
3. Before changing a public symbol, run `impact`. If you change a signature, update every caller it lists.
4. Make the change, then run the tests named by `impact` / the context pack first, and the broader suite if needed.
5. If the context pack lists `open_findings`, read them (`prism audit report` or `.aicontext/audit/findings.json`). If your change fixes one, tell the user, rerun its evidence command, and only if it now passes run `prism audit update <id> --status fixed`.
6. If `prism status` reports stale `AGENTS.md` sections, finish the user's task first, then offer to run the **prism-refresh** skill.

## Outputs

- The requested change, made after reading only the code PRISM pointed to.
- The relevant tests run.
- The index kept current (automatically by hooks, or by `prism update`).

## Guardrails

- **Opt-in only:** never run `prism init`, `prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks in this conversation.
- **Static analysis has blind spots:** it can miss dynamic calls (reflection, `getattr`, dependency injection, string-based dispatch, framework magic). If a context pack looks incomplete, do a **targeted** grep for the symbol name, never a full scan.
- **Budget:** default `--budget 2000`; raise it only when the task clearly spans more code.
- Never load whole JSON artifacts (`symbols.json`, `call_graph.json`, …) into context; query them through `prism`.
- Never edit files in `.aicontext/` by hand. Write only through `prism refresh commit` and `prism audit record/update`.
