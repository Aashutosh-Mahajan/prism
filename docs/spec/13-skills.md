## 13. Shipped Skills — Skill Plans

Skills are the instruction files through which the host agent does PRISM's "thinking" work. They ship in `prism/templates/skills/<name>/SKILL.md` and are installed by `prism init` (with consent) into the agent's skill location (e.g. `.claude/skills/`). For agents without skills, the same procedures are rendered into their rules file (e.g. `.cursor/rules/prism.mdc`).

**Every skill follows the same structure:** frontmatter (`name`, `description` that clearly states when to trigger) → `prism-managed` marker → Purpose → When to use → Preconditions (consent + freshness check) → Procedure (numbered, each step names the exact CLI command and MCP tool) → Outputs → Guardrails. Skills are product code: versioned with PRISM, snapshot-tested, and checked by the skill consistency test (Section 17) so they only reference commands, flags, and fields that exist.

### 13.1 `prism-context` — navigation

| | |
|---|---|
| **Purpose** | Make the agent load only the code a task needs, using the index instead of scanning. |
| **Triggers** | Start of any coding task; any "where is / what calls / what breaks if" question. |
| **Preconditions** | None to check first (a status call is a wasted turn): call `prism task`; if it reports PRISM is not enabled/installed → work normally, never enable. |
| **Procedure** | `prism task "<request>"` → edit from the answer (an exhaustive literal list is not re-grepped) → `context`/`impact` only as follow-ups → run the listed tests. The skill is deliberately short: its text is loaded whenever it triggers. |
| **Outputs** | Edits made with minimal reads; tests run from `impact`; findings marked fixed only with passing evidence. |
| **Guardrails** | Never run init/scan/enable/global install unasked; never load whole JSON artifacts; fall back to targeted grep (not full scan) when static analysis misses dynamic calls; never hand-edit `.aicontext/`. |

### 13.2 `prism-refresh` — narrative upkeep

| | |
|---|---|
| **Purpose** | Keep `AGENTS.md` and module summaries accurate with minimal token spend, by rewriting only sections that drifted. |
| **Triggers** | `prism_status` reports stale sections (offered after the current task is done), or the user asks to refresh the brief. |
| **Preconditions** | PRISM enabled; index fresh (`update` first if not). |
| **Procedure** | `refresh prepare` → read only the packet and referenced context packs → rewrite each stale section within its token limit (keep what's still true) → `refresh commit` per section → report what changed. |
| **Outputs** | Updated narrative regions; drift reset for committed sections. |
| **Guardrails** | Never touch `prism:generated:*` regions or edit `AGENTS.md` directly; state only verified facts; respect the 600-token brief limit. |

### 13.3 `prism-audit` — agent-driven audit

| | |
|---|---|
| **Purpose** | Turn the host agent into an evidence-based auditor using PRISM's prioritization, with no API or external service. |
| **Triggers** | "Audit / review / health-check the codebase", "find bugs", "what's broken", "check before I merge". |
| **Preconditions** | Scope and depth determined; PRISM enabled (if not, ask the user; if they decline, audit without PRISM and report in chat). |
| **Procedure** | 0 scope & safety → 1 preflight (`status`, `audit plan`) → 2 baseline (tests, type check, lint, coverage) → 3 re-verify prior findings → 4 targeted review per target with checklist → 5 prove (repro in `audit/scratch/`) → 6 `audit record` each finding → 7 `audit report` + summary to user. |
| **Outputs** | `audit/findings.json`, `audit/REPORT.md`, new/fixed/persisting diff, chat summary with top findings and next steps. |
| **Guardrails** | Read-mostly; no fixes/commits/pushes unless asked; no destructive or production-touching commands; ask before tests needing network/DB/Docker; repro files only in `audit/scratch/`; never print secrets; `critical`/`high` need confirmed evidence or a stated reason. |

### 13.4 Future skills (not in v1)

`prism-setup` (walks a user through `prism init` choices when they ask for it; installed only by `prism install --global`), `prism-decisions` (records architecture decisions into `.aicontext/decisions/`), `prism-onboard` (produces a human onboarding tour using the graph viewer).

