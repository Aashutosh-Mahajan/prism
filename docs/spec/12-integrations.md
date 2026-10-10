## 12. Host-Agent Integrations

`prism init [--agent claude-code|cursor|codex|generic|auto]` detects or asks which agent is used and installs only files/config. `prism uninstall-integration` removes them cleanly. All installed files carry a `prism-managed` marker so upgrades can rewrite them safely.

| Agent | What `prism init` installs |
|---|---|
| **Claude Code** | `.claude/skills/prism-*/SKILL.md`; hooks in `.claude/settings.json` (SessionStart, UserPromptSubmit, PostToolUse `Edit\|Write\|MultiEdit`); MCP entry in `.mcp.json`; a ~100-token managed block in `CLAUDE.md`. |
| **Codex** | Managed block in `AGENTS.md`; `[mcp_servers.prism]` in `.codex/config.toml` (a managed TOML block; a table the user wrote is left alone); `.codex/hooks.json` (SessionStart, UserPromptSubmit, PostToolUse `apply_patch\|Edit\|Write`). Project `.codex/` loads only for a trusted project; `init` says so. |
| **Gemini CLI** | Managed block in `GEMINI.md`; `.gemini/settings.json` with `mcpServers.prism` and hooks (SessionStart, BeforeAgent, AfterTool `write_file\|replace`; `--format json`, timeouts in ms). |
| **Cursor** | Short always-on `.cursor/rules/prism.mdc`; audit/refresh/decisions as on-request rules (`alwaysApply: false`); `.cursor/mcp.json`; `.cursor/hooks.json` (sessionStart → `additional_context`, afterFileEdit). Cursor's prompt hook cannot add context, so the agent calls the tool. |
| **Antigravity** (experimental) | `.agent/rules/prism.md`, `.agents/skills/prism-context/`; its MCP config is user-level, so `init` prints the entry instead of editing it. |
| **Generic** | Managed block in root `AGENTS.md` describing the CLI commands. |

**Hook output formats:** plain stdout (Claude Code), `{"hookSpecificOutput": {"hookEventName", "additionalContext"}}` (Codex, Gemini CLI), `{"additional_context"}` (Cursor sessionStart); `prism hook <name> --format text|json|cursor [--event NAME]`. Hooks start without importing the full CLI, force UTF-8 on stdin/stdout, and exit 0.

Rules: merge into existing config files, never clobber user content; back up before modifying (`.aicontext/cache/backups/`); idempotent (running `init` twice changes nothing).

### 12.1 Opt-in model — the user decides, per project

PRISM must never run in a project the user hasn't explicitly chosen. Installing the package (`pip install prism-ctx`) changes nothing in any repository.

**Enabling is always an explicit user action:**
- `prism init` is the only way to enable PRISM in a repo. It runs interactively by default: it shows exactly which files it will create or modify (instruction block, hooks, MCP entry, skills, `.gitignore` lines) and asks for confirmation, with per-item choices (e.g. "install hooks? [Y/n]", "register MCP server? [Y/n]"). `--yes` skips prompts for scripted use only.
- The initial `prism scan` runs only when the user confirms it at the end of `init`, or runs it themselves.
- Nothing happens automatically after `init` except what the user accepted (e.g. if they declined hooks, the index updates only when they run `prism update`).

**Per-user consent, even in shared repos.** A repo can have `.aicontext/` and PRISM hooks committed by a teammate. That must not make PRISM run on every contributor's machine without asking. So every hook and the MCP server first check a **local, per-user enable flag**:
- Flag location: a user-level registry `~/.config/prism/repos.toml` (keyed by repo root path + repo ID from `manifest.json`), never a committed file.
- If the flag is absent, `prism hook session-start` prints at most one line into the agent's context ("This repo has a PRISM index. PRISM is not enabled for you here; run `prism enable` if you want to use it.") and does nothing else: no scan, no update, no writes. `prism hook post-edit` exits silently. The MCP server exposes only `prism_status`, which reports "not enabled."
- `prism enable` / `prism disable` toggle the flag for the current repo. `prism init` sets it for the user who ran it.

**Pausing and removing:**
- `prism pause` / `prism resume` stop and restart all automatic activity (hooks become no-ops) without removing anything.
- `prism uninstall-integration` removes every PRISM-managed block, hook, MCP entry, and skill, restoring backups. `prism uninstall-integration --purge` also deletes `.aicontext/`, after confirmation.
- `prism status` always shows the current state: `not initialized`, `initialized · not enabled for you`, `enabled`, or `paused`.

**Optional global setup is also opt-in and never auto-runs.** `prism install --global` (never run implicitly) only adds a short user-level note to the agent's global instruction file (e.g. `~/.claude/CLAUDE.md`): "If a repo has `.aicontext/` and PRISM is enabled for it, use PRISM for navigation. Never run `prism init` or `prism scan` unless the user asks." By default it does **not** make agents suggest PRISM in new repos. Suggestions only happen if the user chooses `--suggest`, and even then the agent may mention it once per repo, and only for large repos, never run it. `prism uninstall --global` removes the note.

**Rules for agents (enforced in every shipped skill and instruction block):**
- Never run `prism init`, `prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks in the current conversation.
- If PRISM is not initialized or not enabled, work normally without it. Don't nag. Mention it at most once, and only when global suggestions are on.
- `prism update` is allowed automatically only in repos where PRISM is enabled for this user (hooks do this; agents without hooks may run it after edits).

### 12.2 How a new agent session discovers PRISM

An agent only knows what is in its context when the session starts, so PRISM has to put itself there. It does this only in repos where the user enabled it, through several layers, so if one is missing another still works:

| Layer | Mechanism | Agents |
|---|---|---|
| 1. Instruction block | Managed block in the file the agent always reads at session start (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/prism.mdc`): "This repo is indexed by PRISM. Read `.aicontext/AGENTS.md`, use `prism search`/`prism context` before exploring files, check `prism status`." | All |
| 2. Session-start hook | `prism hook session-start`: consent check → incremental catch-up → prints the compact brief + freshness line into context. | Claude Code (and others with hooks) |
| 3. Prompt hook | `prism hook user-prompt`: the answer to the user's own request is added to the prompt, so the model's first turn already has the code. | Claude Code, Codex, Gemini CLI |
| 3b. MCP tools | `prism_task` (+ context, impact, status in the lean profile) appear in the agent's tool list. | MCP-capable agents |
| 4. Skill | `prism-context` skill description triggers at the start of coding tasks. | Claude Code |
| 5. Plain files | `.aicontext/AGENTS.md` and JSON are readable with no PRISM install at all. | All, as fallback |

**Hook robustness:** every hook must exit 0 quickly (post-edit returns in ~0.2 s because the update runs detached; user-prompt is bounded to 16 s (installed hook timeout 20) and says nothing on timeout), never print errors into the agent's context, and do nothing if `prism` isn't installed, the repo isn't enabled for this user, or PRISM is paused. A broken or missing PRISM must never break or slow an agent session.

| Situation | What the agent sees |
|---|---|
| Enabled for this user, PRISM installed | Brief injected automatically; skill + MCP guide navigation. |
| Repo initialized by a teammate, not enabled for this user | One line saying PRISM is available and how to enable it. Nothing runs. |
| Committed `.aicontext/` but PRISM not installed | Hook not found → silent. Instruction block still points to `.aicontext/AGENTS.md` as plain files; the agent may use it read-only. |
| Never initialized | No PRISM files, so nothing happens. Only if the user turned on global `--suggest`, the agent may mention PRISM once. |
| Enabled but paused | Hooks are no-ops; `prism status` shows `paused`. The instruction block tells the agent the index may be stale. |
| Enabled, index stale (e.g. after `git pull`, or edits made with no hook) | The next answer checks the working tree and updates the changed files first; the session-start hook also catches up. |

