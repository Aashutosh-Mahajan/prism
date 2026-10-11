# Use PRISM and language servers together

Use `prism task` for ranked orientation, bounded source packets, static callers,
related tests and cross-file impact. Its inferred callers can include ambiguous
name matches. Inspect the resolution markers before making a mechanical rename.

Use your host's language-server tools for exact definitions, references and
symbol rename when the server understands the project's imports and types.
Confirm the workspace and dependencies are loaded; exactness depends on the
server's current project state. Check generated changes with targeted tests.

`prism doctor` reports the main indexed language and recognized enabled Claude
language-server plugins from user and project settings. It also reports known
server executables on PATH when no plugin is recognized. A binary on PATH does
not prove a host has configured it, and an enabled plugin does not prove its
server is running. Unknown host configurations remain unverified. PRISM neither
installs servers nor adds an LSP dependency.

This integration makes no token-savings claim. Use the native benchmark results
for measured claims, rather than transferring another tool's reported savings.
