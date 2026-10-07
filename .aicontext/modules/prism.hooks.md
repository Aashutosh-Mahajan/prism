# Module `prism.hooks`

<!-- prism:generated:facts -->
- Files: prism/hooks/__init__.py, prism/hooks/entry.py, prism/hooks/formats.py, prism/hooks/prompt.py, prism/hooks/runner.py, prism/hooks/update_job.py
- Docstring: Command-line plumbing for host-agent hooks, kept free of typer and rich.
- Public API (by importance):
  - `user_prompt(raw_stdin: str) -> str` — Context to add for the submitted prompt (empty when there is nothing worth adding). (prism/hooks/prompt.py:122)
  - `run_hook(name: str, args: list[str] | None = None) -> None` — Run one hook: read the hook JSON from stdin, act, print what belongs in the agent's (prism/hooks/entry.py:73)
  - `should_retrieve(prompt: str) -> bool` — Is this prompt a request about the code, rather than chat, a command or a confirmation? (prism/hooks/prompt.py:38)
  - `post_edit(raw_stdin: str, background: bool = False) -> None` — Update the index for the edited files. With `background`, hand the update to a detached (prism/hooks/runner.py:206)
  - `session_start(raw_stdin: str) -> str` — Returns the text to inject into the agent's context (may be empty). (prism/hooks/runner.py:87)
  - `render_context(text: str, fmt: str, event: str) -> str` — `text` as the hook should print it for the agent that asked for `fmt`. (prism/hooks/formats.py:15)
  - `edited_paths(payload: dict[str, Any]) -> list[str]` — Files an edit touched, whichever agent reported it. (prism/hooks/runner.py:128)
  - `parse_payload(raw: str) -> dict[str, Any]` (prism/hooks/runner.py:43)
  - `parse_flags(args: list[str]) -> dict[str, str]` — `--format X` / `--event Y` (also `--format=X`) from a hook command line. (prism/hooks/entry.py:57)
  - `background_enabled() -> bool` — Post-edit updates run in a detached process unless `PRISM_HOOK_SYNC=1` asks to wait. (prism/hooks/entry.py:49)
  - `hard_exit() -> None` — Hooks must never linger: flush and exit 0 even if a bounded update is still running. (prism/hooks/entry.py:40)
  - `read_stdin() -> str` (prism/hooks/entry.py:31)
  - … 2 more
- Depends on: `prism`, `prism.consent`, `prism.core`, `prism.discovery`, `prism.incremental`, `prism.navigator.api`, `prism.navigator.freshness`, `prism.navigator.session`, `prism.navigator.store`, `prism.navigator.task_pack`, `prism.writers`
- Used by: `prism`
- Tests: tests/benchmarks/edit_bench.py, tests/integration/test_hooks_mcp.py, tests/integration/test_integrations.py, tests/integration/test_prompt_hook.py
- Entry points: `prism.hooks.update_job.main`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
