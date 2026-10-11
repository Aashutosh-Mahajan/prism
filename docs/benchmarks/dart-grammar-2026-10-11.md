# T45 Dart grammar experiment

Adopt an optional AST parser; keep the dependency-free parser when the grammar
is absent. Install with `pip install prism-ctx[dart]`. The optional dependency
is pinned to `tree-sitter-dart==0.1.0`; its package metadata declares MIT and
links to [the grammar repository](https://github.com/efrenbl/tree-sitter-dart).

The Windows CPython abi3 wheel installed into an isolated target directory,
without changing the base environment. Declaration names, nesting, ranges and
invocations come from the syntax tree. Existing Dart import normalization is
reused. Syntax errors are reported while recoverable declarations are retained.

Nine focused tests passed: the seven existing mobile parser cases, a multiline
Dart declaration with an exact call line, and full artifact equality after two
edits versus a fresh scan. The fixture verifies the `main` caller of `Home`.
Static name resolution still has the existing limitations of Dart's unaliased
library imports; this experiment makes no exact-reference claim.

The grammar is optional and is not vendored into the base wheel. Kotlin and
Swift changes are kept separate from this language change.
