"""Optional Kotlin syntax-tree declarations and invocations."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from prism.parsing.treesitter import Node, TreeSitterParser, _Ctx, _text, _walk


class KotlinTreeSitterParser(TreeSitterParser):
    language = "kotlin"
    function_types = frozenset({"function_declaration"})
    class_types = frozenset({"class_declaration", "object_declaration"})
    decision_types = frozenset(
        {
            "if_expression",
            "when_entry",
            "for_statement",
            "while_statement",
            "do_while_statement",
            "catch_block",
        }
    )

    @staticmethod
    def grammar() -> Any:
        import tree_sitter_kotlin

        return tree_sitter_kotlin.language()

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        for node in _walk(root, lambda n: n.type in self.function_types):
            if self.is_symbol(node):
                yield node, None

    def call_target(self, node: Node) -> str | None:
        if node.type != "call_expression" or not node.named_children:
            return None
        function = node.named_children[0]
        text = _text(function)
        if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", text):
            return text.replace("this.", "self.", 1)
        if function.type == "navigation_expression":
            name = function.named_children[-1]
            return _text(name) if name.type == "identifier" else None
        return None

    def visibility(self, node: Node, name: str) -> str:
        modifiers = next((n for n in node.named_children if n.type == "modifiers"), None)
        return "private" if re.search(r"\b(private|protected)\b", _text(modifiers)) else "public"

    def bases(self, node: Node) -> list[str]:
        return [
            _text(child)
            for holder in node.named_children
            if holder.type == "delegation_specifiers"
            for child in _walk(holder)
            if child.type == "user_type"
        ]

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        from prism.parsing.braces import KotlinParser

        normalizer = KotlinParser()
        for node in root.named_children:
            if node.type == "import":
                ctx.imports.extend(
                    normalizer.imports_of(
                        _text(node), node.start_point[0] + 1, ctx.module, ctx.is_package
                    )
                )

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
            symbol = ctx.symbols[-1]
            modifiers = next((n for n in node.named_children if n.type == "modifiers"), None)
            symbol.is_async = "suspend" in _text(modifiers).split()
