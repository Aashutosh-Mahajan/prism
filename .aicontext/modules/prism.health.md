# Module `prism.health`

<!-- prism:generated:facts -->
- Files: prism/health/__init__.py, prism/health/coverage.py, prism/health/git_intel.py, prism/health/risk.py
- Docstring: Read line coverage per file from an existing coverage report, if there is one.
- Public API (by importance):
  - `read_coverage(root: Path, indexed: set[str]) -> dict[str, float]` (prism/health/coverage.py:24)
  - `git_head(root: Path) -> str | None` (prism/health/git_intel.py:40)
  - `collect_git(root: Path, indexed: set[str], previous: GitIntel | None = None) -> GitIntel` (prism/health/git_intel.py:45)
  - `compute_health(parsed: Iterable[ParsedFile], symbols: dict[str, Symbol], complexity: dict[str, int], module_rank: dict[str, float], tested_files: set[str], tested_symbols: set[str], git: GitIntel | None, coverage: dict[str, float], open_findings: dict[str, int], test_files: set[str]) -> Health` (prism/health/risk.py:34)
  - `smells_by_kind(health: Health) -> dict[str, int]` (prism/health/risk.py:149)
- Depends on: `prism.core`
- Used by: `prism`
- Tests: tests/unit/test_phase3_extractors.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
