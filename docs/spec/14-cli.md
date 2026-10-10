## 14. CLI Surface (complete)

```
prism init [--agent ...] [--no-hooks] [--no-mcp] [--yes]   enable PRISM in this repo (interactive, shows every change first)
prism enable | disable                             per-user consent for this repo (local, never committed)
prism pause | resume                               stop/restart all automatic activity without removing anything
prism uninstall-integration [--purge]              remove all PRISM-managed files (and optionally .aicontext/)
prism install --global [--suggest] | uninstall --global   optional user-level note for agents (never auto-runs)
prism scan [--full] [--lang ...]                    full index build
prism update [--files ...] [--quiet]                incremental update
prism status [--json]                               freshness, drift, stale sections, audit summary
prism brief                                         AGENTS.md + freshness line
prism locate <name> | context <target> | impact <target> | search "<q>" | module <name>
prism task "<request>" [--budget N] [--session ID]  one-call retrieval (Section 8.5)
prism note "<text>" | recall ["<topic>"]           work log: handoff notes, earlier sessions (9.4)
prism refresh prepare [--sections ...] | refresh commit <section> --file <md>
prism audit plan | record | update | report
prism hook session-start | post-edit               called by host-agent hooks (stdin JSON)
prism mcp                                           run MCP server (stdio)
prism migrate                                       upgrade .aicontext/ schemas
prism view [--focus <target>] [--port N]           interactive Obsidian-style graph in the browser (local)
prism graph export --html|--obsidian|--mermaid|--dot|--graphml|--json [--around <t>]
prism doctor                                        diagnose setup (hooks, MCP, schema, git)
```

Exit codes: 0 ok, 1 user error, 2 index missing/stale beyond repair, 3 internal error. Every command supports `--json` where output is structured. Output is quiet and machine-friendly by default in hook mode.

