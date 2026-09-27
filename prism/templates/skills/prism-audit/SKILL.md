---
name: prism-audit
description: Use when the user asks to audit, review, or health-check the codebase (or part of it), find bugs, check what's broken, or verify that tests pass. Runs a prioritized, evidence-based audit using the PRISM index and records findings in .aicontext/audit/.
---
<!-- prism-managed: installed and updated by `prism init`. Local edits are overwritten on upgrade. -->

# PRISM Codebase Audit

## Purpose

You are the auditor. PRISM gives you a prioritized plan, the codebase map, and a place to record findings; you read the code, run the checks, prove each problem, and report. No external services or API calls are involved — everything runs in this workspace.

The audit is **read-mostly**. You do not fix code, commit, push, or change configuration unless the user explicitly asks you to after seeing the report.

## When to use

- The user asks to audit, review, or health-check the codebase or part of it.
- "Find bugs", "what's broken", "are the tests passing", "check my changes before I merge".

## Preconditions

- Scope and depth are determined (step 0).
- PRISM is enabled for this user (step 1). If it isn't, ask; if the user declines, audit without PRISM and report in chat.

## Procedure

### 0. Scope and safety (before doing anything)

1. Determine scope from the user's request. Default mapping:
   - "audit the codebase" → `--scope all --depth standard`
   - "check my recent changes" / "before I merge" → `--scope changed --since <main branch or given ref>`
   - "audit <folder/file>" → `--scope <path>`
   - "quick check" → `--depth quick`; "thorough/deep" → `--depth deep`
2. **Safety rules — apply to every command you run:**
   - Never run commands that touch production systems, real payment/email/SMS providers, or remote databases.
   - Never run destructive commands (dropping databases, deleting files outside `.aicontext/audit/scratch/`, `git reset/clean/push`).
   - Never install packages globally. If tests need dependencies that aren't installed, report it; install into the project's existing virtual environment only if the user agrees.
   - If a test suite needs network, Docker, or a local database, ask the user before running it.
   - Write any new test or repro file **only** under `.aicontext/audit/scratch/`. Don't add files to the project's real test directories unless the user asks.
   - Don't print secrets. If you find one, report its location, never its value.

### 1. Preflight

1. `prism status` — if PRISM is enabled and the index is stale, run `prism update`. If PRISM is not initialized or not enabled for this user, **ask the user** whether to enable it (`prism init` / `prism enable`) before continuing. Never enable or scan on your own. If they decline, run the audit without PRISM: skip plan/record/report and write findings in your reply.
2. `prism audit plan --scope <…> --depth <…>` (MCP: `prism_audit_plan`) then read `.aicontext/audit/audit_plan.json`. It contains:
   - `toolchain`: detected test, lint, type-check, and coverage commands,
   - `targets`: prioritized symbols/files with `score`, `reasons`, and a context-pack target,
   - `smells`: static leads (not findings yet),
   - `dead_code`: candidates,
   - `untested`: high-importance symbols with no mapped tests,
   - `reverify`: previously open findings to re-check.
3. Tell the user in one line what you're about to audit (scope, number of targets, which commands you'll run). If any command in the plan looks risky per Section 0, say so and wait.

### 2. Baseline checks

Run each `toolchain` command that is safe, in this order: tests → type checker → linter → coverage. Capture pass/fail counts and the first relevant lines of each failure.

- Every failing test is a candidate finding. Determine whether it's a real bug, a broken/obsolete test, or an environment problem, and categorize accordingly (`correctness`, `test_gap`, or `config`).
- Don't re-run a flaky test more than twice; record it as flaky with the outputs.
- Linter/type errors: record only those indicating real defects (wrong types passed, undefined names, unreachable code, unused results of important calls). Group pure style issues into a single `maintainability` / `info` finding with a count.

### 3. Re-verify previous findings

For each item in `reverify`, rerun its `evidence.command` (if safe) or re-read the code at its location.
- Fixed → `prism audit update <id> --status fixed` (MCP: `prism_audit_update`)
- Still present → leave open (the report will mark it "persisting").

### 4. Targeted review (the main pass)

Work through `targets` in order. For each one:

1. `prism context <target> --budget 2000` and read only its `read_list`. Use `prism impact <target>` when the target is public or widely used.
2. Review against this checklist, focusing on the `reasons` PRISM gave:
   - **Correctness:** wrong logic, off-by-one, wrong operator, inverted condition, incorrect edge-case handling (empty, None/null, zero, negative, very large, unicode, timezone/DST), float money math.
   - **Error handling:** swallowed or overly broad exceptions, errors converted to wrong return values, missing cleanup on failure paths, retries without limits.
   - **Security:** injection (SQL, shell, template, path traversal), unsafe deserialization, `eval/exec`, missing authz/authn checks on routes, secrets in code, weak crypto/randomness for security purposes, SSRF, unvalidated redirects, overly permissive CORS.
   - **Concurrency & async:** shared mutable state, race conditions, missing `await`, blocking calls in async code, non-atomic check-then-act.
   - **Resources:** unclosed files/connections/sessions, unbounded caches or queues, missing timeouts on network calls.
   - **API contract:** callers (from the context pack) relying on behavior the target doesn't guarantee; signature/return-type mismatches across callers; breaking changes vs. routes/models.
   - **Performance:** N+1 queries, repeated work in loops, quadratic algorithms on large inputs, loading whole datasets into memory.
   - **Tests:** important paths (especially from `untested`) with no test; tests asserting nothing meaningful.
   - **Config:** env vars read without defaults/validation, config keys referenced but never defined (PRISM's `config.json` helps).
3. Turn relevant `smells` for this target into findings only after confirming them in context — a smell alone is not a finding.
4. For `dead_code` candidates, check for dynamic use (entry points, plugin registries, `getattr`, string imports, framework conventions, public API of a library) before reporting. Report as `dead_code` / `low` with confidence `likely` unless you've proven it unreachable.

### 5. Prove it

Every finding needs evidence. Aim for the strongest you can get cheaply:

| Confidence | Evidence required |
|---|---|
| `confirmed` | A command whose output demonstrates the problem: a failing existing test, or a minimal repro test you wrote in `.aicontext/audit/scratch/test_<id>.py` that fails, or a script whose output shows the wrong behavior. |
| `likely` | Specific code reasoning with exact lines and a concrete input/state that triggers the problem, when a repro is impractical (e.g. needs external services). |
| `suspected` | Plausible issue that depends on intent or business rules you can't verify. Say what needs confirming and by whom. |

Rules: repro tests must be minimal, deterministic, offline, and must not modify project files. `critical`/`high` findings should be `confirmed`; if not, include a `reason` explaining why a repro wasn't possible.

### 6. Record each finding

Write one JSON object per finding and pass it to `prism audit record --json <file>` (or via stdin / the `prism_audit_record` MCP tool). Required fields:

```json
{
  "title": "Short, specific statement of the defect",
  "severity": "critical | high | medium | low | info",
  "category": "correctness | security | error_handling | concurrency | resource | performance | api_contract | test_gap | dead_code | maintainability | config",
  "confidence": "confirmed | likely | suspected",
  "file": "path/relative/to/repo.py",
  "lines": [start, end],
  "symbol": "qualified.symbol.id or null",
  "description": "What is wrong, the triggering input/state, and the consequence.",
  "evidence": {"type": "failing_test | repro_script | tool_output | code_reasoning", "command": "…", "output_excerpt": "…"},
  "suggested_fix": "The smallest correct fix, or options if a business decision is needed."
}
```

PRISM assigns the ID, dedupes against existing findings, and rejects invalid records — if it rejects one, fix the fields and retry.

### Severity rubric

- **critical** — exploitable security hole, data loss/corruption, or a core flow completely broken in normal use.
- **high** — wrong results or crashes in realistic scenarios; auth/permission gaps with limited reach; failing tests on the main branch.
- **medium** — bugs in edge cases, missing error handling that degrades behavior, significant performance problems, important untested paths.
- **low** — minor bugs with easy workarounds, dead code, small robustness gaps.
- **info** — style/maintainability observations, grouped where possible.

### 7. Report

1. `prism audit report` (MCP: `prism_audit_report`) → renders `.aicontext/audit/REPORT.md` with a severity summary, per-finding detail, and new / fixed / persisting compared with the last audit.
2. Reply to the user with: scope covered, baseline results (tests passed/failed, type/lint status), counts by severity, the top 3–5 findings in one line each with IDs, anything you couldn't run and why, and a pointer to `REPORT.md`.
3. Offer next steps — e.g. "fix F-012 and F-015", "add tests for the untested items", "deep audit of `payments/`" — but don't start fixing until the user says so.

### If the user asks you to fix findings afterwards

Fix one finding at a time. Use `prism impact` before editing, turn the repro into a real test in the project's test suite if the user agrees, run the evidence command to show it now passes, then `prism audit update <id> --status fixed`.

## Outputs

- `.aicontext/audit/findings.json`: every finding, validated and deduplicated by PRISM.
- `.aicontext/audit/REPORT.md`: severity summary, per-finding detail, and new / fixed / persisting compared with the last audit.
- Repro tests in `.aicontext/audit/scratch/` (gitignored).
- A chat summary: scope, baseline results, counts by severity, top findings with IDs, what couldn't be run and why, suggested next steps.

## Guardrails (summary)

- Read-mostly: no fixes, commits, pushes, or config changes unless the user asks after the report.
- No destructive commands and nothing that touches production, real third-party providers, or remote databases.
- Ask before running tests that need network, Docker, or a database. No global installs.
- New files only under `.aicontext/audit/scratch/`. Never print secret values.
- Every finding needs evidence; `critical`/`high` must be `confirmed` or state why a repro wasn't possible.
- Never run `prism init`, `prism scan`, or `prism enable` without the user's explicit OK.
