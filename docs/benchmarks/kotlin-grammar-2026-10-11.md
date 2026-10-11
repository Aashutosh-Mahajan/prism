# T45 Kotlin grammar experiment

Adopt optional Kotlin AST extraction with `pip install prism-ctx[kotlin]`.
The grammar is pinned to `tree-sitter-kotlin==1.1.0`, declared MIT by its
[package metadata](https://pypi.org/project/tree-sitter-kotlin/1.1.0/).
Its Windows abi3 wheel installed into the scratch grammar directory without
changing the base dependencies. The dependency-free parser remains available.

Nine focused tests passed: existing mobile fixtures and hostile-input cases,
a multiline class method with exact invocation coordinates, and complete
artifact equality after two updates compared with fresh scans. The indexed
fixture verifies the `total` caller of `discount`. Declarations, nesting and
calls come from the syntax tree; existing import normalization is reused.

This is a separate language change from Dart and Swift. No language server or
exact-reference claim is implied by the static call graph.
