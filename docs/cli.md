# CLI reference

Every command accepts `--root PATH` (default: the repository containing the current directory)
and `--help`. Commands with structured output accept `--json`. Human output is compact Markdown;
hook commands are silent.

For normal CLI commands, `--root` can also appear before the command. Task retrieval
accepts `--session` there too: `prism --root PATH --session ID task "request"`.
Command-level options override these defaults. Session defaults apply to task retrieval;
host hooks use the repository and session supplied by their host event.

- [Setup and consent](#setup-and-consent)
- [Index](#index)
- [Navigation](#navigation)
- [Narrative and decisions](#narrative-and-decisions)
- [Audit](#audit)
- [Graph](#graph)
- [Agent plumbing](#agent-plumbing)
- [Exit codes](#exit-codes)

## Setup and consent

### `prism init`

Enable PRISM in this repository. Shows every change first and asks before making it.

| Option | Default | Description |
|---|---|---|
| `--agent` | `auto` | `claude-code`, `cursor`, `codex`, `gemini`, `antigravity`, `generic`, `auto` or `none` |
| `--hooks / --no-hooks` | ask | Install agent hooks (brief at session start, the code a request needs added to the prompt, update after edits) |
| `--mcp / --no-mcp` | ask | Register the MCP server |
| `--git-hooks / --no-git-hooks` | ask | Install git `post-commit`, `post-merge`, `post-checkout` hooks |
| `--scan / --no-scan` | ask | Run the initial scan |
| `--yes`, `-y` | | Skip prompts (for scripts) |

Running `init` twice changes nothing. Existing config files are merged, never overwritten, and
backed up to `.aicontext/cache/backups/` before modification.

### `prism enable` · `prism disable`

Turn PRISM on or off for **you** in this repository. The flag is local
(`~/.config/prism/repos.toml`) and never committed; nothing in the repository changes.

### `prism pause` · `prism resume`

Stop and restart all automatic activity (hooks become no-ops) without removing anything.

### `prism uninstall-integration [--purge]`

Remove every PRISM-managed block, hook, MCP entry and skill, restoring backups. `--purge` also
deletes `.aicontext/` and your consent flag, after confirmation.

### `prism install --global [--suggest]` · `prism uninstall --global`

Add (or remove) a short note in your agent's user-level instructions, for example
`~/.claude/CLAUDE.md`: use PRISM where it is enabled and never run `init` or `scan` unasked.
`--suggest` additionally lets agents mention PRISM once in large repositories without an index.
Never run implicitly.

### `prism doctor`

Diagnose the setup: Python and PRISM versions, `prism` on `PATH`, index and schema versions,
consent, freshness, artifact integrity, MCP SDK, git, parsers and the viewer bundle.

```text
 ✓ python           3.14.4 (win32)
 ✓ prism            0.1.0
 ✓ initialized      /home/you/repo/.aicontext
 ✓ consent          enabled
 ✓ freshness        index fresh
 ✓ artifacts        match the manifest
 ! git              no git history (churn/co-change disabled)
 ✓ languages        javascript, python (counted, not parsed: shell)
 ✓ viewer bundle    present
```

## Index

### `prism scan [--full] [--json]`

Build the full index into `.aicontext/`. Unchanged files reuse cached hashes and parses unless
`--full` is given.

### `prism update [FILE ...] [--files FILE ...] [--quiet] [--json]`

Incremental update: re-parse only changed, added or deleted files. Files known to have changed
may be named as arguments, after `--files`, or with several `--files`; `prism update a.py b.py`,
`prism update --files a.py b.py` and `prism update --files a.py --files b.py` all work. Named
files are always re-hashed. Exits early without writing when nothing changed.

Updates take a lock (`.aicontext/cache/update.lock`), so a hook, a query and a manual update
never write the index at the same time. You rarely need this command: every query checks the
working tree first and brings changed files up to date itself.

### `prism status [--json]`

Consent state, index freshness, drift, stale brief sections and an audit summary.

```text
enabled · index fresh
last update 2026-09-27T15:26:54Z · 23 files · 33 symbols · 3 test files
```

The state line is one of `not initialized`, `initialized · not enabled for you`, `enabled` or
`paused`.

### `prism watch [--interval SECONDS]`

Keep the index fresh while you work, for editors and agents without hooks. Default interval
1.0 s (minimum 0.2). Ctrl+C stops.

### `prism migrate`

Upgrade `.aicontext/` to the installed PRISM version's schema and rebuild the index.

## Navigation

### `prism task "<request>" [--mode auto|overview|code] [--budget N] [--session ID] [--json]`

Start a coding task with one local call. Pass the request in the user's own words, a symbol
name, or a file path. `auto` selects a signature/relationship map for architecture requests
and source for edits. `--mode overview` explicitly requests a compact map (a file path gives
its symbol outline); `--mode code` explicitly requests source. MCP `prism_task` accepts the
same `mode`. Maps are selective and never claim to contain enough source to edit.

Examples: `prism task "repository architecture"`, `prism task src/service.py --mode overview`,
`prism task "fix the cache expiry" --mode code`. Exact source follow-ups support
`src/service.py::Class.method`, `src/service.py:42` (enclosing symbol) and
`src/service.py:42-65` (only that range). The source answer contains:

- **Literals**: every exact occurrence of the strings, names and quantities the request
  mentions, with `file:line` and the line. Quoted strings (`'Something went wrong'`), code names
  (`LIFETIME_MINUTES`, `EmailCode.verify`), numbers with units ("10 minutes", found even as
  `LIFETIME_MINUTES = 10`) and multi-word phrases are searched across the whole indexed source
  through the postings, without scanning the repository. A list marked *exhaustive* covers every
  matching line, so the agent need not grep those strings again. Capped scans and unavailable
  candidate files are explicitly marked limited; their totals are lower bounds. New names are
  reported only after a complete candidate search.
- **Blocks**: the code that best matches the request, with line numbers: a whole function when
  it is small, windows around the matching lines otherwise. Whole files and module headers are
  never returned as an orientation strategy. Cooperating methods in an affordable small class
  can be returned together. Used Python constants/imports/local helpers are included when they
  fit; unrelated file headers are excluded. Body and symbol rankings use reciprocal-rank fusion.
- **Callers** of the symbols the answer is about, with the calling line, plus **tests** that
  mention them and the **impact** (how many symbols and files depend on them).
- **Confidence** (`high`, `medium`, `low`), `sufficient`, and a `Next:` line saying how far to
  trust the answer. `low` says to search narrowly. Partial packets list precise `read_next`
  ranges rather than requiring a repeat of the whole file. Completeness is about the supplied
  evidence, not a guarantee that an edit is correct or static graphs cover dynamic dispatch.

The default budget is 2000 (range 128-32000), using `ceil(characters/4)` across the entire
returned packet, including serialization and metadata. It is an estimate, not the model's token
count; host and tool envelopes are outside it.

Before answering it checks the working tree and brings any changed files up to date (only for a
user PRISM is enabled for), so an edit made without running `prism update` is still seen.
Source is returned only if it matches the indexed hash.

`--session ID` (or `PRISM_SESSION`) remembers which code ranges this session already received;
repeats come back as one-line references instead of the code again. The MCP server does this
for its own lifetime (`repeat=true` forces the full answer).

The query caches (`.aicontext/cache/index-*.sqlite`, `source-v2.sqlite`) are built by `prism scan`
and kept current by updates; they are local and disposable. No model API, embeddings download or
API key is involved.

Targets for the follow-up commands can be a symbol id (`shop.pricing.discounts.apply_discount`),
a file path, `file:line`, a module, or a route (`"GET /orders"`). An ambiguous target returns
ranked candidates instead of guessing.

### `prism brief [--full]`

Print the compact session brief and a one-line freshness status. This is what the session-start
hook injects: the project's languages and run/test/lint commands, any narrative a human or agent
has written, and the one-line way to use PRISM. Generated overviews, placeholders and module
rankings are left out (a repository overview does not help an agent find files faster and costs
tokens every turn). `--full` prints the whole `.aicontext/AGENTS.md`.

### `prism search QUERY [--limit N] [--semantic] [--json]`

Ranked free-text search over names, qualified ids, docstrings, paths and routes (BM25, local).
`--limit` 1–100, default 10. `--semantic` blends in a local embedding model and needs
`prism-ctx[semantic]`.

### `prism locate NAME [--limit N] [--json]`

Resolve a name to candidates with `file:lines`: exact match, then qualified suffix, then fuzzy.

### `prism context TARGET [--budget N] [--depth 1|2] [--with-source] [--json]`

Build a context pack: location and signature, summary, risk, open findings, and a read list of
callers, callees, tests and related code that fits the budget (default 2,000 tokens, minimum
100). `--with-source` inlines the target's body when it fits.

### `prism impact TARGET [--depth 1-6] [--json]`

Blast radius: dependents grouped by distance (default depth 3) and the tests to run.

```text
# Impact: `shop.pricing.discounts.apply_discount`
8 dependent symbols across 5 files

## Distance 1
- `shop.checkout.cart.Cart.total`
- files: src/shop/checkout/cart.py
…
## Tests to run
- tests/test_cart.py
- tests/test_discounts.py
- tests/test_orders.py
```

### `prism module NAME [--json]`

Show a module summary from `.aicontext/modules/`.

## Narrative and decisions

### `prism refresh prepare [--sections NAME ...]`

Emit what the agent needs to rewrite each stale section of `AGENTS.md` or a module summary:
relevant context, the structural diff since the last refresh, and a token budget per section.

### `prism refresh commit SECTION --file FILE [--json]`

Validate and write one section (`purpose`, `architecture`, `conventions` or `modules/<name>`),
resetting its drift. Generated regions can never be overwritten this way.

### `prism decision add | list | show`

Record, list and print architecture decisions in `.aicontext/decisions/`.

## Audit

See [audit.md](audit.md) for the full workflow.

| Command | Purpose |
|---|---|
| `prism audit plan [--scope all\|changed\|PATH] [--since REF] [--depth quick\|standard\|deep] [--json]` | Write `audit/audit_plan.json`: toolchain commands, prioritized targets, smells, dead-code candidates, prior findings to re-verify |
| `prism audit record --json FILE\|-` | Validate and store a finding; assigns `F-###` ids and dedupes |
| `prism audit update ID --status open\|fixed\|wontfix\|false_positive [--note TEXT] [--json]` | Change a finding's status |
| `prism audit report [--json]` | Render `audit/REPORT.md` with a diff against the previous audit |

## Graph

### `prism view [--focus TARGET] [--depth 1-4] [--port N] [--no-open]`

Start the local graph viewer on `127.0.0.1` (random free port by default, one-time token in the
URL) and open it in your browser. `--focus` opens the local graph around a target. See
[viewer.md](viewer.md).

### `prism graph export`

| Option | Description |
|---|---|
| `--html FILE` | Self-contained HTML viewer (works offline, no server) |
| `--obsidian DIR` | Obsidian vault: one note per module or file with `[[wikilinks]]` and tags |
| `--mermaid` · `--dot` · `--graphml` · `--json` | Text formats, to stdout or `--out FILE` |
| `--around TARGET` · `--depth 1-4` | Only the neighbourhood of a target |
| `--level package\|file\|symbol` | Level of detail (default `file`) |
| `--layer import\|call\|tests\|cochange` | Which relationships (default `import`) |
| `--symbols` | HTML and Obsidian: include symbol-level nodes |
| `--with-graph-colors` | Obsidian: add risk colour groups to the graph view |

Mermaid and DOT exports without `--around` are capped at 150 nodes to stay readable.

## Agent plumbing

| Command | Used by |
|---|---|
| `prism mcp [--profile lean\|full]` | The agent, from `.mcp.json`: runs the MCP server over stdio. `lean` (default) exposes `prism_status`, `prism_task`, `prism_context`, `prism_impact`; `full` adds search, locate, brief, module and the refresh/audit/decision tools. Also `PRISM_MCP_PROFILE`. |
| `prism hook session-start [--format text\|json\|cursor] [--event NAME]` | Session-start hook: consent check, catch-up update, prints the compact brief |
| `prism hook user-prompt [--format ...] [--event NAME]` | Prompt hook: looks up the user's request and adds the matching code to the prompt; silent when there is nothing worth adding |
| `prism hook post-edit` | Post-edit hook: starts an index update for the edited files in a detached process and returns at once; silent, always exits 0 |

`--format text` prints plain context (Claude Code); `json` prints
`{"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}` (Codex, Gemini CLI);
`cursor` prints `{"additional_context": ...}`. Hooks start without importing the full command
line, always speak UTF-8, and always exit 0. `PRISM_HOOK_SYNC=1` makes `post-edit` wait for the
update instead of detaching.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | User error (bad input, not initialized, not found, ambiguous target) |
| 2 | Index missing or stale beyond repair |
| 3 | Internal error |

Hook commands always exit 0 so a PRISM problem can never break an agent session.
