# CLI reference

Every command accepts `--root PATH` (default: the repository containing the current directory)
and `--help`. Commands with structured output accept `--json`. Human output is compact Markdown;
hook commands are silent.

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
| `--agent` | `auto` | `claude-code`, `cursor`, `codex`, `generic`, `auto` or `none` |
| `--hooks / --no-hooks` | ask | Install agent hooks (session brief, update after edits) |
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

### `prism update [--files FILE ...] [--quiet] [--json]`

Incremental update: re-parse only changed, added or deleted files. `--files` names files known
to have changed (they are always re-hashed). Exits early without writing when nothing changed.

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

Targets can be a symbol id (`shop.pricing.discounts.apply_discount`), a file path, `file:line`,
a module, or a route (`"GET /orders"`). An ambiguous target returns ranked candidates instead of
guessing.

### `prism brief`

Print `.aicontext/AGENTS.md` and a one-line freshness status. This is what the session-start
hook injects.

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
| `prism mcp` | The agent, from `.mcp.json`: runs the MCP server over stdio |
| `prism hook session-start` | Agent session-start hook: consent check, catch-up update, prints the brief |
| `prism hook post-edit` | Agent post-edit hook: updates the index for the edited file; silent, always exits 0 |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | User error (bad input, not initialized, not found, ambiguous target) |
| 2 | Index missing or stale beyond repair |
| 3 | Internal error |

Hook commands always exit 0 so a PRISM problem can never break an agent session.
