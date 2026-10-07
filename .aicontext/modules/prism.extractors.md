# Module `prism.extractors`

<!-- prism:generated:facts -->
- Files: prism/extractors/__init__.py, prism/extractors/base.py, prism/extractors/blast_radius.py, prism/extractors/config_keys.py, prism/extractors/dead_code.py, prism/extractors/entry_points.py, prism/extractors/models.py, prism/extractors/project.py, prism/extractors/routes.py, prism/extractors/tests_map.py, prism/extractors/toolchain.py
- Docstring: Extractor interface and registry.
- Public API (by importance):
  - `detect_toolchain(root: Path) -> list[dict[str, Any]]` — Ordered: tests -> type checker -> linter -> coverage (the audit's baseline order), (prism/extractors/toolchain.py:158)
  - `brief_commands(root: Path) -> dict[str, str]` — One command per kind and folder, for the brief (coverage is audit-only). (prism/extractors/toolchain.py:172)
  - `detect_commands(root: Path, has_tests: bool) -> dict[str, str]` — The brief's commands: the shared toolchain detector, plus pytest as a fallback when (prism/extractors/project.py:54)
  - `is_test_file(path: str, test_dirs: Sequence[str]) -> bool` — Python (test_*.py, *_test.py, conftest.py), JS/TS (*.test.ts, *.spec.js, __tests__/), (prism/extractors/tests_map.py:14)
  - `parse_route_decorator(decorator: str) -> tuple[list[str], str] | None` — `app.post("/orders")` -> (["POST"], "/orders"); None if not a route decorator. (prism/extractors/routes.py:27)
  - `project_dirs(root: Path) -> list[str]` — The root ("") plus nested folders that hold their own project markers. (prism/extractors/toolchain.py:137)
  - `class ExtractorContext` (prism/extractors/base.py:22)
  - `class BlastRadiusExtractor(Extractor[BlastRadius])` (prism/extractors/blast_radius.py:15)
  - `class ConfigExtractor(Extractor[list[ConfigKey]])` (prism/extractors/config_keys.py:9)
  - `class DeadCodeExtractor(Extractor[list[DeadCode]])` (prism/extractors/dead_code.py:20)
  - `class EntryPointsExtractor(Extractor[list[EntryPoint]])` (prism/extractors/entry_points.py:24)
  - `class ModelsExtractor(Extractor[list[ModelInfo]])` (prism/extractors/models.py:35)
  - … 8 more
- Depends on: `prism`, `prism.core`, `prism.discovery`, `prism.graph`
- Used by: `prism`, `prism.audit`, `prism.navigator.store`
- External: tomli
- Tests: tests/benchmarks/tokens.py, tests/integration/test_audit.py, tests/unit/test_extractors.py, tests/unit/test_phase3_extractors.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
