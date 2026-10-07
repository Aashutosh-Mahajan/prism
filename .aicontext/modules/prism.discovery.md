# Module `prism.discovery`

<!-- prism:generated:facts -->
- Files: prism/discovery/__init__.py, prism/discovery/language.py, prism/discovery/scanner.py
- Docstring: Language detection by extension, falling back to the shebang line.
- Public API (by importance):
  - `discover(root: Path, config: PrismConfig, known: Mapping[str, Mapping[str, Any]] | None = None, resniff: bool = True) -> list[SourceFile]` — Select source files. `known` (manifest `files`) lets unchanged files skip hashing. (prism/discovery/scanner.py:120)
  - `detect_language(path: str, first_line: str | None = None) -> str | None` — Return a language name, or None if the file is not source code PRISM tracks. (prism/discovery/language.py:42)
  - `looks_minified(head: bytes) -> bool` — True when the first bytes read like a minified bundle (very long average line). (prism/discovery/scanner.py:65)
  - `hash_file(path: Path) -> str` (prism/discovery/scanner.py:108)
- Depends on: `prism`, `prism.core`
- Used by: `prism`, `prism.extractors`, `prism.hooks`
- External: pathspec
- Tests: tests/unit/test_discovery.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
