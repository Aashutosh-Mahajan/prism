# Troubleshooting

Start with `prism doctor`. It checks the installation, the index, consent, hooks, the MCP SDK,
git, parsers and the viewer bundle, and says what to do about anything that isn't right.

```text
 ✓ python           3.14.4 (win32)
 ✓ prism            0.1.0
 ✓ prism on PATH    /home/you/.local/bin/prism
 ✓ initialized      /home/you/repo/.aicontext
 ✓ manifest schema  schema 1.0
 ✓ consent          enabled
 ✓ freshness        index fresh
 ✓ artifacts        match the manifest
 ✓ mcp sdk          installed
 ! git              no git history (churn/co-change disabled)
 ✓ languages        javascript, python (counted, not parsed: shell)
 ✓ viewer bundle    present
```

## Common problems

### "PRISM is not enabled for you here"

A teammate initialized the repository. Run `prism enable` if you want to use it. The flag is
local to your machine.

### The agent doesn't seem to use PRISM

1. `prism status` should say `enabled`, not `paused` or `not enabled for you`.
2. Check the integration exists: `.claude/skills/prism-context/SKILL.md`, the hooks in
   `.claude/settings.json`, and the `prism` entry in `.mcp.json` (or `.cursor/rules/prism.mdc`).
   Re-run `prism init` to reinstall; it is idempotent.
3. Make sure `prism` is on the `PATH` the agent uses (`prism doctor` shows it). Hooks and the MCP
   server are started by the agent, not by your shell.
4. Restart the agent session so it reloads settings and MCP servers.

### The index is stale

Run `prism update`. Without hooks, keep `prism watch` running in a terminal, or install the git
hooks with `prism init --git-hooks`. After upgrading PRISM, run `prism migrate` if `status` or
`doctor` mentions a schema change.

Hook problems are never shown to the agent; look in `.aicontext/cache/hook.log`.

### The brief says "Not written yet"

The narrative sections (purpose, architecture, conventions) are written by your agent. Ask it to
"refresh the PRISM brief"; the `prism-refresh` skill fills them in.

### Search doesn't find what I mean

- Try the function or file name; exact names rank first.
- Use `prism locate <name>` for names and `prism search` for descriptions.
- Tests and migrations rank below application code unless your query mentions them.
- With `prism-ctx[semantic]` and a local model configured, `prism search --semantic` blends in
  meaning-based matches.

### A language isn't parsed

Python is built in. JavaScript, TypeScript, Go and Java need `pip install "prism-ctx[treesitter]"`
followed by `prism scan`. Other languages are counted but not parsed yet.

### Symbols with names like `a`, `I` or `$` appear

That is minified code. Current versions skip minified bundles; run `prism update` or
`prism scan` to drop them, and add generated folders to `.prismignore` if needed.

### The viewer says it can't reach the server

The `prism view` process stopped, or you are looking at an old tab. Start it again and open the
new link it prints; the token in the URL changes every time.

### The viewer is empty

The current filters may hide everything; use *Reset filters* in the empty state. Some layers need
data: *Changed together* needs git history, and *Routes* needs a web framework's routes.

### `prism init` changed a file I care about

Every modified file was backed up to `.aicontext/cache/backups/`. `prism uninstall-integration`
removes everything PRISM added and restores the backups.

## Reporting a bug

Open an issue with `prism --version`, your OS and Python version, the command, what you expected,
what happened, and the `prism doctor` output. Don't include secrets or private source code.
