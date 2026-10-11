"""Optional Swift declarations, extensions and invocation syntax trees."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from prism.core.models import ImportRef
from prism.parsing.treesitter import Node, TreeSitterParser, _Ctx, _text, _walk


class SwiftTreeSitterParser(TreeSitterParser):
    language = "swift"
    class_types = frozenset({"class_declaration", "protocol_declaration"})
    function_types = frozenset({"function_declaration", "protocol_function_declaration"})
    method_types = frozenset({"init_declaration", "deinit_declaration"})
    decision_types = frozenset(
        {
            "if_statement",
            "for_statement",
            "while_statement",
            "repeat_while_statement",
            "switch_entry",
            "catch_block",
            "ternary_expression",
            "guard_statement",
        }
    )

    @staticmethod
    def grammar() -> Any:
        import tree_sitter_swift

        return tree_sitter_swift.language()

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        for node in _walk(root, lambda n: n.type in self.function_types | self.method_types):
            if self.is_symbol(node):
                # An extension contributes methods to a type, not a replacement type definition.
                if node.type in self.class_types and _text(node).lstrip().startswith("extension "):
                    continue
                yield node, None

    def symbol_name(self, node: Node) -> str:
        if node.type == "init_declaration":
            return "init"
        if node.type == "deinit_declaration":
            return "deinit"
        names = node.children_by_field_name("name")
        return _text(names[0]) if names else ""

    def call_target(self, node: Node) -> str | None:
        if node.type != "call_expression" or not node.named_children:
            return None
        text = _text(node.named_children[0])
        if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", text):
            return text
        return None

    def visibility(self, node: Node, name: str) -> str:
        modifiers = next((n for n in node.named_children if n.type == "modifiers"), None)
        return "private" if re.search(r"\b(private|fileprivate)\b", _text(modifiers)) else "public"

    def bases(self, node: Node) -> list[str]:
        return [
            _text(child.child_by_field_name("inherits_from"))
            for child in node.named_children
            if child.type == "inheritance_specifier"
        ]

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        for node in root.named_children:
            if node.type == "import_declaration":
                identifiers = [n for n in node.named_children if n.type == "identifier"]
                if identifiers:
                    ctx.imports.append(
                        ImportRef(_text(identifiers[-1]), None, None, 0, node.start_point[0] + 1)
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
            symbol.is_async = "async" in _text(node).split("{", 1)[0].split()
