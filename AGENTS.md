<!-- prism-managed:start -->
## PRISM code index

Use PRISM context supplied with the prompt directly; do not retrieve it again.
Otherwise, for unknown code use `prism task "<user request>"` (MCP: `prism_task`) once.
Architecture requests return a compact map; edits return source, local definitions, callers and tests.
Use returned evidence directly. If partial, read only `read_next` ranges; if weak, search narrowly.
Literal lists are exhaustive only when marked complete. Do not follow a good packet with a repo scan.
For a map explicitly use `--mode overview`; for source use `--mode code` (MCP: `mode`).
Known one-line edits need no broad orientation. Queries refresh the index.

If it reports PRISM is not enabled or not installed, work normally. Never run `prism init`,
`prism scan`, `prism enable`, or `prism install --global` unless the user explicitly asks.
<!-- prism-managed:end -->
