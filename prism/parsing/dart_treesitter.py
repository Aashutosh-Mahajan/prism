"""Optional Dart grammar: AST declarations, ranges and invocation selectors."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from prism.core.models import CallRef, ParsedFile, SymbolKind
from prism.core.tokens import estimate_tokens
from prism.parsing.treesitter import Node, TreeSitterParser, _Ctx, _text, _walk


class DartTreeSitterParser(TreeSitterParser):
    language = "dart"
    function_types = frozenset({"function_signature"})
    class_types = frozenset(
        {"class_definition", "mixin_declaration", "enum_declaration", "extension_declaration"}
    )
    method_types = frozenset({"getter_signature", "setter_signature", "constructor_signature"})
    decision_types = frozenset(
        {
            "if_statement",
            "for_statement",
            "while_statement",
            "do_statement",
            "switch_case",
            "catch_clause",
            "conditional_expression",
        }
    )

    @staticmethod
    def grammar() -> Any:
        import tree_sitter_dart

        return tree_sitter_dart.language()

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        for node in _walk(root, lambda n: n.type == "function_body"):
            if self.is_symbol(node):
                outer = (
                    node.parent if node.parent.type in {"method_signature", "declaration"} else None
                )
                yield node, outer

    def _body(self, node: Node) -> Node | None:
        anchor = node.parent if node.parent.type == "method_signature" else node
        following = anchor.next_named_sibling
        return following if following is not None and following.type == "function_body" else None

    def calls_in(self, node: Node) -> list[CallRef]:
        body = self._body(node) if self.is_symbol(node) else None
        calls: set[CallRef] = set()
        for sub in _walk(body or node):
            if sub.type != "identifier":
                continue
            target = _text(sub)
            following = sub.next_named_sibling
            while following is not None and following.type == "selector":
                if any(part.type == "argument_part" for part in following.named_children):
                    calls.add(CallRef(target, sub.start_point[0] + 1))
                else:
                    names = [_text(part) for part in _walk(following) if part.type == "identifier"]
                    if names:
                        target += "." + names[-1]
                following = following.next_named_sibling
        return sorted(calls, key=lambda call: (call.line, call.target))

    def add_symbol(
        self,
        node: Node,
        outer: Node | None,
        ctx: _Ctx,
        name: str | None = None,
        qual: tuple[str, str | None] | None = None,
    ) -> None:
        before = len(ctx.symbols)
        super().add_symbol(node, outer, ctx, name, qual)
        if len(ctx.symbols) > before:
            anchor = outer or node
            previous = anchor.prev_named_sibling
            if (
                previous is not None
                and previous.type == "documentation_comment"
                and previous.end_point[0] >= anchor.start_point[0] - 1
            ):
                symbol = ctx.symbols[-1]
                symbol.lines = (previous.start_point[0] + 1, symbol.lines[1])
        body = self._body(node)
        if len(ctx.symbols) > before and body is not None:
            symbol = ctx.symbols[-1]
            symbol.lines = (symbol.lines[0], body.end_point[0] + 1)
            symbol.tokens_est = estimate_tokens(
                "\n".join(ctx.lines[symbol.lines[0] - 1 : symbol.lines[1]])
            )
            symbol.complexity = self.complexity(body)
            symbol.is_async = "async" in _text(body).split("{", 1)[0].split()

    def signature(self, node: Node, name: str, kind: SymbolKind) -> str:
        return " ".join(_text(node).split("{", 1)[0].split())[:300]

    def visibility(self, node: Node, name: str) -> str:
        return "private" if name.startswith("_") else "public"

    def bases(self, node: Node) -> list[str]:
        return [
            _text(part)
            for child in node.named_children
            if child.type in {"superclass", "interfaces", "mixins", "on_clause"}
            for part in _walk(child)
            if part.type == "type_identifier"
        ]

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        from prism.parsing.braces import DartParser

        # Existing normalization resolves package and relative module paths.
        parsed = DartParser().parse("", ctx.source, ctx.module, ctx.is_package)
        ctx.imports.extend(parsed.imports)

    def call_target(self, node: Node) -> str | None:
        return None  # Dart invocation arguments are sibling selector nodes.

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        result = super().parse(path, source, module, is_package)
        result.module_calls = [
            call
            for call in result.module_calls
            if not any(
                start <= call.line <= end for start, end in (s.lines for s in result.symbols)
            )
        ]
        return result
