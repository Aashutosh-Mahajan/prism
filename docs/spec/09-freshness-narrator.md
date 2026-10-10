## 9. Freshness & Narrator — Keeping the Context Alive

### 9.1 Update triggers (all optional; installed by `prism init` only if the user accepts them)

| Trigger | Action |
|---|---|
| Every navigator query (CLI and MCP) | **Working-tree check**: compare the tree with the manifest (a stat walk; unchanged files are not re-read) and, if the user has enabled PRISM and not paused it, update just the changed files under the update lock before answering (up to 300 files). Freshness therefore never depends on a hook or on the agent remembering `prism update`. |
| Host-agent hook after file edits (Claude Code/Codex `PostToolUse`, Gemini `AfterTool`, Cursor `afterFileEdit`) | `prism hook post-edit` → reads the hook JSON (any agent's shape, including Codex `apply_patch` text), starts `prism update` for those files in a **detached process** and returns at once (~0.2 s). Must never block or fail the agent. |
| Session start hook | `prism hook session-start` → bounded catch-up of anything changed outside the agent (e.g. `git pull`), then prints the **compact brief** into the agent's context, plus a ≤ 140-token summary of the most recent other session from the work log (Section 9.4). |
| Prompt hook (Claude Code/Codex `UserPromptSubmit`, Gemini `BeforeAgent`) | `prism hook user-prompt` → runs `prism task` for the user's own words and adds the answer to the prompt (≤ `prompt_budget`, default 1,200 tokens). Silent for greetings, confirmations, slash commands and weak matches; code is sent once per session; if the query caches are cold it warms them in the background and stays silent once. Opt-out: `prompt_context = false` or `PRISM_PROMPT_CONTEXT=0`. Agents whose prompt hook cannot inject context (Cursor) rely on the tool. |
| Git `post-commit` / `post-merge` / `post-checkout` hooks | `prism update --quiet` |
| Manual / file watcher | `prism update`, `prism watch` |

Index writes are serialized by a cross-process lock; artifacts are written atomically (retrying a Windows sharing violation briefly); the manifest is written last.

Verify exact hook config formats against the current docs of each host agent at implementation time; keep them in `prism/integrations/<agent>/` only.

### 9.2 Drift scoring — what counts as a "major/important change"

Every update computes a **structural diff** and adds weighted points to the drift score of each affected `AGENTS.md` section / module summary:

| Change | Weight (default) |
|---|---|
| New or deleted module/package | 5 |
| New/removed/renamed **public** symbol | 2 |
| Public signature change | 2 |
| New/removed route, model, or config key | 3 |
| Import-graph edges added/removed between modules | 1 per edge (cap 5) |
| Symbol enters/leaves global top-20 by PageRank | 3 |
| New dependency in `pyproject`/`package.json`/etc. | 3 |
| Private body-only edits | 0 (index updates, narrative does not) |

When a section's score ≥ threshold (default 8, configurable), it's marked **stale** in `manifest.json`. `prism brief` and `prism status` surface stale sections and tell the agent to run the `prism-refresh` skill. Formatting-only and comment-only changes never add drift.

### 9.3 `AGENTS.md` structure

Hybrid: PRISM writes facts, the agent writes prose, inside marked regions. PRISM must never overwrite narrative regions; the agent must never edit generated regions.

```markdown
# <Project> — Agent Brief
<!-- prism:generated:facts -->   stack, languages, entry points, commands (test/lint/run), top modules by rank
<!-- prism:narrative:purpose -->  what the project does, for whom (2–3 sentences)
<!-- prism:narrative:architecture --> how the pieces fit, main data flow
<!-- prism:narrative:conventions -->  patterns to follow, gotchas
<!-- prism:generated:navigation -->   "Before reading files, use prism search/context …"
```

**What is injected is not the whole file.** Research on repository context files (Gloaguen et al., 2026, *Evaluating AGENTS.md*) found that generated overviews do not help agents find the relevant files faster and raise cost by about 20% with no gain in success, because agents follow them with extra exploration. So the session brief an agent receives (`prism brief`, the SessionStart hook) is **compact**: the title, the `Languages` and `Commands` facts, any narrative section someone has actually written, and one line on how to use PRISM (≈ 100-150 tokens). Placeholders, key dependencies, entry points and module rankings stay in the file but are not injected. The narrative sections are **optional**: they are written only if a human or agent chooses to (the `prism-refresh` skill), and staleness is reported only for sections that exist.

`prism refresh prepare [--sections ...]` emits exactly what the agent needs to write each stale section (relevant context packs, structural diff since last narration, token budget per section). `prism refresh commit <section> --file <md>` validates length/markers and writes it, resetting that section's drift. This keeps the agent's work bounded and verifiable.

### 9.4 Work log — continuity between sessions

The index says how the code is built; it does not say what the last session was doing. Hooks therefore append small events per agent session to `.aicontext/cache/worklog/<session>.jsonl` (local, gitignored, pruned after 30 days, written only when enabled and not paused): the request (prompt hook), each edited file with the first line of new text (post-edit hook; resolved to the enclosing symbol when displayed), the symbols retrieved, and optional one-line notes (`prism note`). The next session start includes a short summary of the most recent other session; `prism task` answers add `history` lines when an earlier session changed the same code and the line fits the budget; `prism recall` searches older sessions. Off with `worklog = false` / `PRISM_WORKLOG=0`.

