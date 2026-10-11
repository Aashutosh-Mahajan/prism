# T45 Swift grammar experiment

Adopt optional Swift AST extraction with `pip install prism-ctx[swift]`.
The grammar is pinned to `tree-sitter-swift==0.7.3`, declared MIT by its
[package metadata](https://pypi.org/project/tree-sitter-swift/0.7.3/).
The Windows abi3 wheel installed into an isolated target directory. The base
installation retains the existing dependency-free parser.

Nine focused tests passed: existing Swift types, initializers, privacy,
inheritance and extensions, hostile-input cases, a multiline method with exact
invocation coordinates, and full artifact equality after two updates versus
fresh scans. The indexed fixture verifies `total` calling `discount`. Extensions
add methods without replacing the original class declaration and its bases.

This experiment is separate from Dart and Kotlin. The grammar is an optional
package, and no exact-reference or language-server claim is made.
