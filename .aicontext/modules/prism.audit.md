# Module `prism.audit`

<!-- prism:generated:facts -->
- Files: prism/audit/__init__.py, prism/audit/plan.py, prism/audit/record.py, prism/audit/report.py, prism/audit/store.py, prism/audit/toolchain_detect.py
- Docstring: `prism audit plan`: a prioritized, evidence-oriented plan for the host agent.
- Public API (by importance):
  - `audit_dir(root: Path) -> Path` (prism/audit/store.py:18)
  - `build_plan(root: Path, scope: str = 'all', since: str | None = None, depth: str = 'standard') -> dict[str, Any]` (prism/audit/plan.py:114)
  - `record_finding(root: Path, finding: dict[str, Any]) -> dict[str, Any]` (prism/audit/record.py:106)
  - `findings_path(root: Path) -> Path` (prism/audit/store.py:22)
  - `update_status(root: Path, finding_id: str, status: str, note: str | None = None) -> dict[str, Any]` (prism/audit/record.py:157)
  - `load_findings(root: Path) -> dict[str, Any]` (prism/audit/store.py:30)
  - `write_findings(root: Path, data: dict[str, Any]) -> None` (prism/audit/store.py:48)
  - `build_report(root: Path) -> dict[str, Any]` (prism/audit/report.py:66)
  - `changed_files(root: Path, since: str | None) -> set[str]` — Files changed since `since` (committed), plus uncommitted and untracked changes. (prism/audit/plan.py:86)
  - `smell_score(smells: list[dict[str, Any]]) -> float` (prism/audit/plan.py:47)
  - `plan_path(root: Path) -> Path` (prism/audit/store.py:26)
  - `default_base(root: Path) -> str | None` (prism/audit/plan.py:78)
  - … 2 more
- Depends on: `prism`, `prism.core`, `prism.extractors`, `prism.writers`
- Used by: `prism`, `prism.mcp`
- External: jsonschema
- Tests: tests/integration/test_audit.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
