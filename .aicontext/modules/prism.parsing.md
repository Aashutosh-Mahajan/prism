# Module `prism.parsing`

<!-- prism:generated:facts -->
- Files: prism/parsing/__init__.py, prism/parsing/base_parser.py, prism/parsing/modules.py, prism/parsing/python_ast.py, prism/parsing/python_facts.py, prism/parsing/smells.py, prism/parsing/treesitter.py
- Docstring: Parser interface and registry. One parser per language.
- Public API (by importance):
  - `get_parser(language: str) -> BaseParser | None` (prism/parsing/base_parser.py:25)
  - `dotted_name(expr: ast.expr) -> str | None` — `a.b.c` -> "a.b.c"; `super().x` -> "super().x"; anything else -> None. (prism/parsing/python_ast.py:31)
  - `module_name(path: str, source_roots: Sequence[str] = ('src',), language: str = 'python') -> tuple[str, bool]` — Return (module_name, is_package) for a source file path. (prism/parsing/modules.py:12)
  - `register_parser(parser: BaseParser) -> None` (prism/parsing/base_parser.py:21)
  - `class PythonAstParser(BaseParser)` (prism/parsing/python_ast.py:214)
  - `available() -> bool` (prism/parsing/treesitter.py:37)
  - `parsers() -> list[BaseParser]` — Every tree-sitter parser whose grammar package is installed. (prism/parsing/treesitter.py:987)
  - `class JavaScriptParser(TreeSitterParser)` (prism/parsing/treesitter.py:349)
  - `class TypeScriptParser(JavaScriptParser)` (prism/parsing/treesitter.py:609)
  - `resolve_js_specifier(importer: str, importer_is_package: bool, spec: str) -> str` — `./b` from module `web.a` -> `web.b`; bare specifiers stay (dotted); `@/x` -> `x`. (prism/parsing/treesitter.py:331)
  - `env_reads(nodes: list[ast.stmt] | ast.AST) -> list[EnvRead]` (prism/parsing/python_facts.py:66)
  - `class_fields(node: ast.ClassDef) -> list[tuple[str, str]]` (prism/parsing/python_facts.py:47)
  - … 10 more
- Depends on: `prism.core`
- Used by: `prism`
- External: tree_sitter, tree_sitter_go, tree_sitter_java, tree_sitter_javascript, tree_sitter_typescript
- Tests: tests/unit/test_graph.py, tests/unit/test_python_parser.py, tests/unit/test_treesitter.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
