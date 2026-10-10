## 10. Auditor — Agent-Driven Codebase Audit

### 10.1 Concept

PRISM ships an **audit skill** (`prism-audit`) — a precise set of instructions that tells the host coding agent how to audit this codebase: what to check, in what order, how to prove each finding, and how to record it. PRISM contributes what it's good at (prioritization from the index, detecting test/lint commands, schema validation, report rendering, history diffing). The host agent contributes what it's good at (reading code, reasoning about bugs, running and writing tests). **No API. No separate service.**

### 10.2 Commands

| Command | Purpose |
|---|---|
| `prism audit plan [--scope all\|changed\|<path>] [--since <git-ref>] [--depth quick\|standard\|deep]` | Writes `audit/audit_plan.json`: detected toolchain commands (tests, linters, type checker, coverage), prioritized targets with reasons and context-pack IDs, static smells, dead-code candidates, untested high-rank symbols, previous open findings to re-verify. |
| `prism audit record --json <finding.json>` (or stdin) | Validates and appends/updates a finding in `audit/findings.json`. Assigns stable IDs (`F-###`), dedupes by (file, symbol, category, fingerprint). |
| `prism audit update <id> --status fixed\|wontfix\|false_positive` | Lifecycle changes. |
| `prism audit report` | Renders `audit/REPORT.md` (summary, severity table, per-finding detail, diff vs previous audit: new / fixed / persisting), archives to `audit/history/`. |
| MCP: `prism_audit_plan`, `prism_audit_record`, `prism_audit_report` | Same, for MCP-capable agents. |

### 10.3 Audit plan prioritization

Target score = risk (complexity × churn × low coverage) + centrality (PageRank) + blast radius size + recency of change + static smell count + open prior findings. Depth caps the number of targets (quick ≈ 10, standard ≈ 30, deep ≈ 100).

Static smell detectors (cheap, deterministic, feed the plan — they are *leads*, not findings): bare/broad `except`, swallowed exceptions, mutable default args, `eval`/`exec`/`pickle.loads`/`subprocess(shell=True)`, SQL built by string formatting, hardcoded secret patterns, `TODO/FIXME/HACK`, very long functions, unreachable code, unused imports/symbols, missing awaits (where detectable).

### 10.4 Finding schema

```json
{
  "id": "F-012",
  "title": "Discount applied twice when coupon and sale overlap",
  "severity": "high",
  "category": "correctness",
  "confidence": "confirmed",
  "file": "src/pricing/discounts.py",
  "lines": [61, 74],
  "symbol": "pricing.discounts.apply_discount",
  "description": "Sale price is computed first, then the coupon percentage is applied to the original price and both reductions are summed.",
  "evidence": {"type": "failing_test", "command": "pytest .aicontext/audit/scratch/test_f012.py -q", "output_excerpt": "AssertionError: 72.0 != 81.0"},
  "suggested_fix": "Apply coupon to the post-sale price, or pick max(sale, coupon) per business rule — confirm rule with owner.",
  "status": "open",
  "found_in_audit": "2026-09-27T10:42:00Z",
  "fingerprint": "sha256:…"
}
```

- `severity`: `critical | high | medium | low | info` (rubric defined in the skill).
- `category`: `correctness | security | error_handling | concurrency | resource | performance | api_contract | test_gap | dead_code | maintainability | config`.
- `confidence`: `confirmed` (reproduced: failing test/command output), `likely` (strong static reasoning), `suspected` (needs human judgment). **Only `confirmed` may be `critical`/`high` without an explicit reason field.**

### 10.5 Integration back into navigation

Open findings appear in context packs and `prism status`. Fixed findings are re-verified on the next audit. `health.json` risk incorporates open findings.

The full audit procedure lives in `prism/templates/skills/prism-audit/SKILL.md` (shipped with this spec). Treat it as product code: version it, test it (see Section 17), and keep it consistent with the CLI.

