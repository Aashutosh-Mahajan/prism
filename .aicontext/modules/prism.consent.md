# Module `prism.consent`

<!-- prism:generated:facts -->
- Files: prism/consent/__init__.py, prism/consent/registry.py
- Docstring: Per-user, per-repo consent flags (CLAUDE.md Section 12.1).
- Public API (by importance):
  - `get_entry(root: Path) -> RepoEntry | None` (prism/consent/registry.py:84)
  - `registry_path() -> Path` (prism/consent/registry.py:43)
  - `config_home() -> Path` (prism/consent/registry.py:38)
  - `load_registry() -> dict[str, RepoEntry]` (prism/consent/registry.py:51)
  - `repo_key(root: Path) -> str` (prism/consent/registry.py:47)
  - `class RepoEntry` (prism/consent/registry.py:31)
  - `set_entry(root: Path, entry: RepoEntry | None) -> None` (prism/consent/registry.py:88)
  - `repo_state(root: Path, repo_id: str | None) -> RepoState` — Consent state for this user. `repo_id` comes from the manifest (None if absent). (prism/consent/registry.py:98)
  - `save_registry(entries: dict[str, RepoEntry]) -> None` (prism/consent/registry.py:71)
  - `class RepoState(str, Enum)` (prism/consent/registry.py:24)
- Depends on: `prism.writers`
- Used by: `prism`, `prism.hooks`, `prism.mcp`, `prism.navigator.freshness`
- External: tomli
- Tests: tests/integration/test_cli.py, tests/integration/test_freshness.py, tests/integration/test_hooks_mcp.py, tests/integration/test_integrations.py, tests/integration/test_prompt_hook.py, tests/unit/test_consent.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
