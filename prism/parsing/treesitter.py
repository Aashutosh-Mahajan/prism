"""Tree-sitter parsers for JavaScript, TypeScript, Go, and Java (optional extra).

Installed with `pip install prism-ctx[treesitter]`. Each language maps its
syntax onto the same normalized `ParsedFile` the Python parser produces, so
the symbol table, graphs, navigator, audit, and viewer work unchanged.

Import targets are emitted as absolute dotted module names (level 0):
relative JS/TS specifiers are resolved against the importing module, Go
import paths become dotted directory names, Java imports are already dotted.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from prism.core.models import (
    CallRef,
    EnvRead,
    ImportRef,
    ParsedFile,
    ParsedSymbol,
    Smell,
    SymbolKind,
)
from prism.core.textio import decode_source
from prism.core.tokens import estimate_tokens
from prism.parsing.base_parser import BaseParser

_TODO = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")

Node = Any  # tree_sitter.Node (untyped third-party)


def available() -> bool:
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        return False
    return True


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    raw: bytes = node.text
    return decode_source(raw)


def _lines(node: Node) -> tuple[int, int]:
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _walk(node: Node, stop: Callable[[Node], bool] | None = None) -> Iterator[Node]:
    """Pre-order walk; does not descend into nodes for which `stop` is true (except the root)."""
    stack = [node]
    first = True
    while stack:
        cur = stack.pop()
        yield cur
        if not first and stop is not None and stop(cur):
            continue
        first = False
        stack.extend(reversed(cur.children))


def _doc_comment(node: Node) -> str:
    prev = node.prev_sibling
    if prev is None or "comment" not in prev.type or prev.end_point[0] < node.start_point[0] - 1:
        return ""
    raw = _text(prev)
    if _TODO.search(raw.splitlines()[0] if raw else ""):
        return ""
    for line in raw.splitlines():
        cleaned = line.strip().lstrip("/*").rstrip("*/").strip().lstrip("*").strip()
        if cleaned and not cleaned.startswith("@"):
            return cleaned
    return ""


@dataclass
class _Ctx:
    source: bytes
    lines: list[str]
    module: str
    is_package: bool
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    smells: list[Smell] = field(default_factory=list)


class TreeSitterParser(BaseParser):
    """Shared machinery. Subclasses describe their language's node types."""

    language = ""
    grammar: Callable[[], Any]
    function_types: frozenset[str] = frozenset()
    class_types: frozenset[str] = frozenset()
    method_types: frozenset[str] = frozenset()
    decision_types: frozenset[str] = frozenset()
    logical_operators = frozenset({"&&", "||", "??"})

    def __init__(self) -> None:
        import tree_sitter

        self._parser = tree_sitter.Parser(tree_sitter.Language(self.grammar()))

    # --- hooks for subclasses --------------------------------------------------------------

    def module_override(self, path: str, root: Node, module: str) -> str:
        return module

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        raise NotImplementedError

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        """(definition node, enclosing node to read the doc comment/decorators from)."""
        raise NotImplementedError

    def call_target(self, node: Node) -> str | None:
        raise NotImplementedError

    def local_types(self, node: Node) -> dict[str, str]:
        return {}

    def env_read(self, node: Node) -> EnvRead | None:
        return None

    # --- shared -----------------------------------------------------------------------------

    def is_symbol(self, node: Node) -> bool:
        return (
            node.type in self.function_types
            or node.type in self.class_types
            or node.type in self.method_types
        )

    def complexity(self, node: Node) -> int:
        score = 1
        for sub in _walk(node, lambda n: n is not node and self.is_symbol(n)):
            if sub.type in self.decision_types:
                score += 1
            elif sub.type == "binary_expression":
                op = sub.child_by_field_name("operator")
                if op is not None and _text(op) in self.logical_operators:
                    score += 1
        return score

    def calls_in(self, node: Node) -> list[CallRef]:
        calls: set[CallRef] = set()
        for sub in _walk(
            node,
            lambda n: n is not node and (n.type in self.class_types or n.type in self.method_types),
        ):
            target = self.call_target(sub)
            if target:
                calls.add(CallRef(target, sub.start_point[0] + 1))
        return sorted(calls, key=lambda c: (c.line, c.target))

    def env_reads_in(self, node: Node) -> list[EnvRead]:
        reads = {r for sub in _walk(node) if (r := self.env_read(sub)) is not None}
        return sorted(reads, key=lambda r: (r.line, r.key))

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        text = decode_source(source)
        line_count = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        tree = self._parser.parse(source)
        root = tree.root_node
        module = self.module_override(path, root, module)
        result = ParsedFile(path, self.language, module, is_package, line_count, "")
        if root.has_error:
            # Tree-sitter recovers from errors, so valid parts of a broken file are still indexed,
            # but the file is reported as having a syntax error like any other parser.
            bad = next((n for n in _walk(root) if n.is_error or n.is_missing), None)
            line = bad.start_point[0] + 1 if bad is not None else 1
            result.parse_error = f"SyntaxError: syntax error near line {line}"
            if not root.children:
                return result
        ctx = _Ctx(source, text.splitlines(), module, is_package)
        self.collect_imports(root, ctx)
        for node, outer in self.symbol_nodes(root):
            self.add_symbol(node, outer, ctx)
        seen: dict[str, int] = {}
        for i, sym in enumerate(ctx.symbols):
            seen[sym.qualname] = i
        result.symbols = [s for i, s in enumerate(ctx.symbols) if seen[s.qualname] == i]
        result.imports = sorted(
            set(ctx.imports), key=lambda r: (r.line, r.module, r.name or "", r.alias or "")
        )
        top_level = [
            c for c in root.children if not self.is_symbol(c) and c.type != "export_statement"
        ]
        result.module_calls = sorted(
            {c for n in top_level for c in self.calls_in(n)}, key=lambda c: (c.line, c.target)
        )
        result.module_env_reads = sorted(
            {r for n in top_level for r in self.env_reads_in(n)}, key=lambda r: (r.line, r.key)
        )
        first = root.children[0] if root.children else None
        if first is not None and "comment" in first.type:
            result.doc = _doc_comment_text(_text(first))
        smells = list(ctx.smells)
        for sub in _walk(root):
            if "comment" in sub.type:
                m = _TODO.search(_text(sub))
                if m:
                    smells.append(
                        Smell("todo", sub.start_point[0] + 1, _text(sub).strip("/* \n")[:120])
                    )
        result.smells = sorted(set(smells), key=lambda s: (s.line, s.kind, s.detail))
        result.names_used = sorted(
            {
                _text(n)
                for n in _walk(root)
                if n.type
                in ("identifier", "property_identifier", "field_identifier", "type_identifier")
            }
        )
        return result

    def symbol_name(self, node: Node) -> str:
        return _text(node.child_by_field_name("name"))

    def signature(self, node: Node, name: str, kind: SymbolKind) -> str:
        if kind == "class":
            return _text(node).split("{", 1)[0].strip().splitlines()[0][:200]
        params = _text(node.child_by_field_name("parameters")) or "()"
        ret = (
            node.child_by_field_name("return_type")
            or node.child_by_field_name("result")
            or node.child_by_field_name("type")
        )
        ret_text = (
            _text(ret).lstrip(":").strip()
            if ret is not None and node.type not in self.class_types
            else ""
        )
        sig = f"{name}{params}"
        if ret_text and ret_text != "void":
            sig += f" -> {ret_text}"
        return " ".join(sig.split())[:300]

    def visibility(self, node: Node, name: str) -> str | None:
        return None

    def decorators(self, node: Node, outer: Node | None) -> list[str]:
        out = []
        for holder in (node, outer):
            if holder is None:
                continue
            for child in holder.children:
                if child.type == "decorator":
                    out.append(_text(child).lstrip("@"))
        return out

    def bases(self, node: Node) -> list[str]:
        return []

    def fields_of(self, node: Node) -> list[tuple[str, str]]:
        return []

    def parent_qualname(self, node: Node, name: str) -> tuple[str, str | None]:
        """(qualname, parent qualname) by walking up to enclosing classes."""
        parents = []
        cur = node.parent
        while cur is not None:
            if cur.type in self.class_types:
                parents.append(self.symbol_name(cur))
            cur = cur.parent
        parents.reverse()
        if parents:
            parent = ".".join(parents)
            return f"{parent}.{name}", parent
        return name, None

    def add_symbol(
        self,
        node: Node,
        outer: Node | None,
        ctx: _Ctx,
        name: str | None = None,
        qual: tuple[str, str | None] | None = None,
    ) -> None:
        name = name or self.symbol_name(node)
        if not name:
            return
        if node.type in self.class_types:
            kind: SymbolKind = "class"
        elif node.type in self.method_types:
            kind = "method"
        else:
            kind = "function"
        qualname, parent = qual or self.parent_qualname(node, name)
        if kind == "function" and parent is not None:
            kind = "method"
        anchor = outer or node
        start = anchor.start_point[0] + 1
        end = node.end_point[0] + 1
        body = node if kind != "class" else None
        ctx.symbols.append(
            ParsedSymbol(
                name=name,
                qualname=qualname,
                kind=kind,
                lines=(start, end),
                signature=self.signature(node, name, kind),
                doc=_doc_comment(anchor),
                decorators=self.decorators(node, outer),
                bases=self.bases(node) if kind == "class" else [],
                calls=self.calls_in(node) if body is not None else [],
                parent=parent,
                tokens_est=estimate_tokens("\n".join(ctx.lines[start - 1 : end])),
                local_types=self.local_types(node) if body is not None else {},
                complexity=self.complexity(node) if body is not None else 1,
                fields=self.fields_of(node) if kind == "class" else [],
                env_reads=self.env_reads_in(node) if body is not None else [],
                is_async=_text(node).lstrip().startswith(("async ", "export async")),
                visibility=self.visibility(node, name),
            )
        )


def _doc_comment_text(raw: str) -> str:
    for line in raw.splitlines():
        cleaned = line.strip().lstrip("/*").rstrip("*/").strip().lstrip("*").strip()
        if cleaned:
            return cleaned
    return ""


# --- JavaScript / TypeScript -------------------------------------------------------------------


def resolve_js_specifier(importer: str, importer_is_package: bool, spec: str) -> str:
    """`./b` from module `web.a` -> `web.b`; bare specifiers stay (dotted); `@/x` -> `x`."""
    spec = spec.strip()
    for ext in (".tsx", ".ts", ".jsx", ".mjs", ".cjs", ".js"):
        if spec.endswith(ext):
            spec = spec[: -len(ext)]
            break
    if spec.endswith("/index"):
        spec = spec[: -len("/index")]
    if spec.startswith("."):
        base = importer.split(".") if importer_is_package else importer.split(".")[:-1]
        joined = posixpath.normpath(posixpath.join("/".join(base) or ".", spec))
        return ".".join(p for p in joined.split("/") if p and p != ".")
    if spec.startswith(("@/", "~/")):
        spec = spec[2:]
    return spec.replace("/", ".")


class JavaScriptParser(TreeSitterParser):
    language = "javascript"
    function_types = frozenset({"function_declaration", "generator_function_declaration"})
    class_types = frozenset(
        {
            "class_declaration",
            "abstract_class_declaration",
            "interface_declaration",
            "enum_declaration",
        }
    )
    method_types = frozenset({"method_definition", "method_signature", "abstract_method_signature"})
    decision_types = frozenset(
        {
            "if_statement",
            "for_statement",
            "for_in_statement",
            "while_statement",
            "do_statement",
            "switch_case",
            "catch_clause",
            "ternary_expression",
        }
    )

    @staticmethod
    def grammar() -> Any:
        import tree_sitter_javascript

        return tree_sitter_javascript.language()

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        for child in root.children:
            outer = None
            node = child
            if child.type == "export_statement":
                decl = child.child_by_field_name("declaration")
                if decl is None:
                    continue
                outer, node = child, decl
            yield from self._definitions(node, outer)

    def _definitions(self, node: Node, outer: Node | None) -> Iterator[tuple[Node, Node | None]]:
        if node.type in self.function_types:
            yield node, outer
        elif node.type in self.class_types:
            yield node, outer
            body = node.child_by_field_name("body")
            for member in body.named_children if body is not None else []:
                if member.type in self.method_types:
                    yield member, None
                elif member.type in ("public_field_definition", "field_definition"):
                    value = member.child_by_field_name("value")
                    if value is not None and value.type in (
                        "arrow_function",
                        "function_expression",
                        "function",
                    ):
                        yield member, None
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for decl in node.named_children:
                value = (
                    decl.child_by_field_name("value")
                    if decl.type == "variable_declarator"
                    else None
                )
                if value is not None and value.type in (
                    "arrow_function",
                    "function_expression",
                    "function",
                    "generator_function",
                ):
                    yield decl, outer or node

    def symbol_name(self, node: Node) -> str:
        if node.type in ("public_field_definition", "field_definition"):
            return _text(node.child_by_field_name("property") or node.child_by_field_name("name"))
        return _text(node.child_by_field_name("name"))

    def add_symbol(
        self,
        node: Node,
        outer: Node | None,
        ctx: _Ctx,
        name: str | None = None,
        qual: tuple[str, str | None] | None = None,
    ) -> None:
        if node.type in ("variable_declarator", "public_field_definition", "field_definition"):
            fn = node.child_by_field_name("value")
            name = self.symbol_name(node)
            qual = self.parent_qualname(node, name)
            if fn is not None:
                # Treat `const f = (...) => ...` like a function declaration named f.
                super().add_symbol(node, outer, ctx, name, qual)
                sym = ctx.symbols[-1]
                sym.signature = f"{name}{_text(fn.child_by_field_name('parameters')) or '(' + _text(fn.child_by_field_name('parameter')) + ')'}"
                ret = fn.child_by_field_name("return_type")
                if ret is not None:
                    sym.signature += f" -> {_text(ret).lstrip(':').strip()}"
                sym.kind = "method" if qual[1] else "function"
            return
        super().add_symbol(node, outer, ctx, name, qual)

    def visibility(self, node: Node, name: str) -> str | None:
        if name.startswith("#"):
            return "private"
        for child in node.children:
            if child.type == "accessibility_modifier":
                return "private" if _text(child) in ("private", "protected") else "public"
        return None

    def bases(self, node: Node) -> list[str]:
        out: list[str] = []
        for sub in _walk(node, lambda n: n.type == "class_body"):
            if sub.type in ("extends_clause", "implements_clause", "extends_type_clause"):
                out.extend(
                    _text(v)
                    for v in sub.named_children
                    if v.type
                    in (
                        "identifier",
                        "member_expression",
                        "type_identifier",
                        "nested_type_identifier",
                    )
                )
        return [b.split("<")[0] for b in out]

    def _dotted(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type in ("identifier", "property_identifier", "type_identifier"):
            return _text(node)
        if node.type == "this":
            return "self"
        if node.type == "super":
            return "super()"
        if node.type == "member_expression":
            obj = self._dotted(node.child_by_field_name("object"))
            prop = node.child_by_field_name("property")
            return f"{obj}.{_text(prop)}" if obj and prop is not None else None
        return None

    def call_target(self, node: Node) -> str | None:
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "identifier" and _text(fn) == "require":
                return None
            return self._dotted(fn)
        if node.type == "new_expression":
            return self._dotted(node.child_by_field_name("constructor"))
        return None

    def local_types(self, node: Node) -> dict[str, str]:
        types: dict[str, str] = {}
        for sub in _walk(node, lambda n: n is not node and self.is_symbol(n)):
            if sub.type in ("required_parameter", "optional_parameter"):
                pat, ann = sub.child_by_field_name("pattern"), sub.child_by_field_name("type")
                if pat is not None and ann is not None and ann.named_children:
                    t = ann.named_children[0]
                    if t.type in ("type_identifier", "nested_type_identifier"):
                        types[_text(pat)] = _text(t)
            elif sub.type == "variable_declarator":
                value = sub.child_by_field_name("value")
                if value is not None and value.type == "new_expression":
                    ctor = self._dotted(value.child_by_field_name("constructor"))
                    if ctor:
                        types.setdefault(_text(sub.child_by_field_name("name")), ctor)
        types.pop("self", None)
        return dict(sorted(types.items()))

    def env_read(self, node: Node) -> EnvRead | None:
        if (
            node.type == "member_expression"
            and _text(node.child_by_field_name("object")) == "process.env"
        ):
            return EnvRead(_text(node.child_by_field_name("property")), node.start_point[0] + 1)
        if (
            node.type == "subscript_expression"
            and _text(node.child_by_field_name("object")) == "process.env"
        ):
            idx = node.child_by_field_name("index")
            if idx is not None and idx.type == "string":
                return EnvRead(_text(idx).strip("'\"`"), node.start_point[0] + 1)
        return None

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        def add(spec: str, name: str | None, alias: str | None, line: int) -> None:
            module = resolve_js_specifier(ctx.module, ctx.is_package, spec)
            if not module:
                return
            if name is None and alias is None:
                alias = module.rsplit(".", 1)[-1]
            ctx.imports.append(ImportRef(module, name, alias, 0, line))

        for node in _walk(root, lambda n: self.is_symbol(n)):
            line = node.start_point[0] + 1
            if node.type in ("import_statement", "export_statement"):
                source = node.child_by_field_name("source")
                if source is None:
                    continue
                spec = _text(source).strip("'\"`")
                clause_found = False
                for child in node.named_children:
                    if child.type == "import_clause":
                        clause_found = True
                        for part in child.named_children:
                            if part.type == "identifier":
                                add(spec, "default", _text(part), line)
                            elif part.type == "namespace_import":
                                ident = next(
                                    (c for c in part.named_children if c.type == "identifier"), None
                                )
                                add(spec, None, _text(ident) or None, line)
                            elif part.type == "named_imports":
                                for spec_node in part.named_children:
                                    if spec_node.type == "import_specifier":
                                        nm = _text(spec_node.child_by_field_name("name"))
                                        al = _text(spec_node.child_by_field_name("alias")) or None
                                        add(spec, nm, al, line)
                    elif child.type == "export_clause":
                        clause_found = True
                        for spec_node in child.named_children:
                            if spec_node.type == "export_specifier":
                                nm = _text(spec_node.child_by_field_name("name"))
                                al = _text(spec_node.child_by_field_name("alias")) or None
                                add(spec, nm, al, line)
                if not clause_found:
                    add(spec, "*" if node.type == "export_statement" else None, None, line)
            elif node.type == "call_expression":
                fn = node.child_by_field_name("function")
                args = node.child_by_field_name("arguments")
                if (
                    fn is not None
                    and _text(fn) in ("require", "import")
                    and args is not None
                    and args.named_children
                ):
                    first = args.named_children[0]
                    if first.type == "string":
                        parent = node.parent
                        alias = None
                        if parent is not None and parent.type == "variable_declarator":
                            target = parent.child_by_field_name("name")
                            if target is not None and target.type == "identifier":
                                alias = _text(target)
                            elif target is not None and target.type == "object_pattern":
                                for prop in target.named_children:
                                    nm = _text(prop.child_by_field_name("key") or prop)
                                    add(_text(first).strip("'\"`"), nm, None, line)
                                continue
                        add(_text(first).strip("'\"`"), None, alias, line)
        for node in _walk(root):
            if (
                node.type == "call_expression"
                and _text(node.child_by_field_name("function")) == "eval"
            ):
                ctx.smells.append(Smell("dangerous_call", node.start_point[0] + 1, "eval()"))


class TypeScriptParser(JavaScriptParser):
    language = "typescript"

    def __init__(self, tsx: bool = False) -> None:
        self._tsx = tsx
        super().__init__()

    def grammar(self) -> Any:  # type: ignore[override]
        import tree_sitter_typescript

        return (
            tree_sitter_typescript.language_tsx()
            if self._tsx
            else tree_sitter_typescript.language_typescript()
        )


class TypeScriptDispatcher(BaseParser):
    """`.ts` and `.tsx` need different grammars; pick by extension."""

    language = "typescript"

    def __init__(self) -> None:
        self._ts = TypeScriptParser(tsx=False)
        self._tsx = TypeScriptParser(tsx=True)

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        parser = self._tsx if path.endswith(".tsx") else self._ts
        return parser.parse(path, source, module, is_package)


class JsxAwareJavaScriptParser(BaseParser):
    """The JavaScript grammar handles JSX; this wrapper exists for symmetry with TypeScript."""

    language = "javascript"

    def __init__(self) -> None:
        self._js = JavaScriptParser()

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        return self._js.parse(path, source, module, is_package)


# --- Go ------------------------------------------------------------------------------------------


class GoParser(TreeSitterParser):
    language = "go"
    function_types = frozenset({"function_declaration"})
    class_types = frozenset({"type_spec"})
    method_types = frozenset({"method_declaration"})
    decision_types = frozenset(
        {
            "if_statement",
            "for_statement",
            "expression_case",
            "type_case",
            "communication_case",
        }
    )
    logical_operators = frozenset({"&&", "||"})

    @staticmethod
    def grammar() -> Any:
        import tree_sitter_go

        return tree_sitter_go.language()

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        for child in root.children:
            if child.type in ("function_declaration", "method_declaration"):
                yield child, None
            elif child.type == "type_declaration":
                for spec in child.named_children:
                    if spec.type == "type_spec":
                        yield spec, child

    def receiver_type(self, node: Node) -> str | None:
        recv = node.child_by_field_name("receiver")
        if recv is None:
            return None
        for sub in _walk(recv):
            if sub.type == "type_identifier":
                return _text(sub)
        return None

    def parent_qualname(self, node: Node, name: str) -> tuple[str, str | None]:
        if node.type == "method_declaration":
            owner = self.receiver_type(node)
            if owner:
                return f"{owner}.{name}", owner
        return name, None

    def visibility(self, node: Node, name: str) -> str | None:
        return "public" if name[:1].isupper() else "private"

    def signature(self, node: Node, name: str, kind: SymbolKind) -> str:
        if kind == "class":
            t = node.child_by_field_name("type")
            return f"type {name} {t.type.replace('_type', '') if t is not None else ''}".strip()
        return super().signature(node, name, kind)

    def fields_of(self, node: Node) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for sub in _walk(node):
            if sub.type == "field_declaration":
                t = _text(sub.child_by_field_name("type"))
                for nm in sub.children_by_field_name("name"):
                    out.append((_text(nm), t))
        return out

    def call_target(self, node: Node) -> str | None:
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            return self._dotted(fn)
        if node.type == "composite_literal":
            t = node.child_by_field_name("type")
            if t is not None and t.type in ("type_identifier", "qualified_type"):
                return _text(t)
        return None

    def _dotted(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type in ("identifier", "field_identifier", "package_identifier", "type_identifier"):
            return _text(node)
        if node.type == "selector_expression":
            operand = self._dotted(node.child_by_field_name("operand"))
            fld = node.child_by_field_name("field")
            return f"{operand}.{_text(fld)}" if operand and fld is not None else None
        if node.type == "qualified_type":
            return _text(node)
        return None

    def local_types(self, node: Node) -> dict[str, str]:
        types: dict[str, str] = {}
        recv = node.child_by_field_name("receiver")
        owner = self.receiver_type(node)
        if recv is not None and owner:
            for sub in _walk(recv):
                if sub.type == "parameter_declaration":
                    for nm in sub.children_by_field_name("name"):
                        types[_text(nm)] = owner
        params = node.child_by_field_name("parameters")
        for sub in _walk(params) if params is not None else []:
            if sub.type == "parameter_declaration":
                t = sub.child_by_field_name("type")
                tname = (
                    next((_text(x) for x in _walk(t) if x.type == "type_identifier"), None)
                    if t is not None
                    else None
                )
                if tname:
                    for nm in sub.children_by_field_name("name"):
                        types[_text(nm)] = tname
        for sub in _walk(node):
            if sub.type == "short_var_declaration":
                left, right = sub.child_by_field_name("left"), sub.child_by_field_name("right")
                if left is None or right is None:
                    continue
                for lhs, rhs in zip(left.named_children, right.named_children, strict=False):
                    lit = (
                        rhs.named_children[0]
                        if rhs.type == "unary_expression" and rhs.named_children
                        else rhs
                    )
                    if lit.type == "composite_literal":
                        t = lit.child_by_field_name("type")
                        if t is not None:
                            types.setdefault(_text(lhs), _text(t))
        return dict(sorted(types.items()))

    def env_read(self, node: Node) -> EnvRead | None:
        if node.type == "call_expression" and _text(node.child_by_field_name("function")) in (
            "os.Getenv",
            "os.LookupEnv",
        ):
            args = node.child_by_field_name("arguments")
            if (
                args is not None
                and args.named_children
                and args.named_children[0].type == "interpreted_string_literal"
            ):
                return EnvRead(_text(args.named_children[0]).strip('"'), node.start_point[0] + 1)
        return None

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        for node in _walk(root):
            if node.type == "import_spec":
                path = _text(node.child_by_field_name("path")).strip('"`')
                alias_node = node.child_by_field_name("name")
                alias = _text(alias_node) if alias_node is not None else path.rsplit("/", 1)[-1]
                if alias in ("_", "."):
                    alias = path.rsplit("/", 1)[-1]
                ctx.imports.append(
                    ImportRef(path.replace("/", "."), None, alias, 0, node.start_point[0] + 1)
                )


# --- Java ----------------------------------------------------------------------------------------


class JavaParser(TreeSitterParser):
    language = "java"
    function_types = frozenset()
    class_types = frozenset(
        {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
    )
    method_types = frozenset({"method_declaration", "constructor_declaration"})
    decision_types = frozenset(
        {
            "if_statement",
            "for_statement",
            "enhanced_for_statement",
            "while_statement",
            "do_statement",
            "catch_clause",
            "switch_label",
            "ternary_expression",
        }
    )
    logical_operators = frozenset({"&&", "||"})

    @staticmethod
    def grammar() -> Any:
        import tree_sitter_java

        return tree_sitter_java.language()

    def module_override(self, path: str, root: Node, module: str) -> str:
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        for child in root.named_children:
            if child.type == "package_declaration":
                pkg = next(
                    (
                        _text(c)
                        for c in child.named_children
                        if c.type in ("scoped_identifier", "identifier")
                    ),
                    "",
                )
                return f"{pkg}.{stem}" if pkg else stem
        return stem

    def symbol_nodes(self, root: Node) -> Iterator[tuple[Node, Node | None]]:
        for node in _walk(root, lambda n: n.type in self.method_types):
            if node.type in self.class_types or node.type in self.method_types:
                yield node, None

    def _modifiers(self, node: Node) -> Node | None:
        return next((c for c in node.children if c.type == "modifiers"), None)

    def visibility(self, node: Node, name: str) -> str | None:
        mods = self._modifiers(node)
        words = _text(mods).split() if mods is not None else []
        return "private" if "private" in words else "public"

    def decorators(self, node: Node, outer: Node | None) -> list[str]:
        mods = self._modifiers(node)
        if mods is None:
            return []
        return [
            _text(c).lstrip("@")
            for c in mods.named_children
            if c.type in ("marker_annotation", "annotation")
        ]

    def signature(self, node: Node, name: str, kind: SymbolKind) -> str:
        if kind == "class":
            return super().signature(node, name, kind)
        mods = self._modifiers(node)
        static = "static " if mods is not None and "static" in _text(mods).split() else ""
        return static + super().signature(node, name, kind)

    def bases(self, node: Node) -> list[str]:
        out: list[str] = []
        for field_name in ("superclass", "interfaces"):
            holder = node.child_by_field_name(field_name)
            if holder is not None:
                out.extend(
                    _text(t)
                    for t in _walk(holder)
                    if t.type in ("type_identifier", "scoped_type_identifier")
                )
        return out

    def fields_of(self, node: Node) -> list[tuple[str, str]]:
        body = node.child_by_field_name("body")
        out: list[tuple[str, str]] = []
        for member in body.named_children if body is not None else []:
            if member.type == "field_declaration":
                t = _text(member.child_by_field_name("type"))
                for decl in member.children_by_field_name("declarator"):
                    out.append((_text(decl.child_by_field_name("name")), t))
        return out

    def _dotted(self, node: Node | None) -> str | None:
        if node is None:
            return None
        if node.type in ("identifier", "type_identifier"):
            return _text(node)
        if node.type == "this":
            return "self"
        if node.type == "super":
            return "super()"
        if node.type in ("field_access", "scoped_identifier"):
            obj = self._dotted(
                node.child_by_field_name("object") or node.child_by_field_name("scope")
            )
            fld = node.child_by_field_name("field") or node.child_by_field_name("name")
            return f"{obj}.{_text(fld)}" if obj and fld is not None else None
        return None

    def call_target(self, node: Node) -> str | None:
        if node.type == "method_invocation":
            name = _text(node.child_by_field_name("name"))
            obj = node.child_by_field_name("object")
            if obj is None:
                return name
            base = self._dotted(obj)
            return f"{base}.{name}" if base else None
        if node.type == "object_creation_expression":
            t = node.child_by_field_name("type")
            return _text(t).split("<")[0] if t is not None else None
        return None

    def local_types(self, node: Node) -> dict[str, str]:
        types: dict[str, str] = {}
        for sub in _walk(node, lambda n: n is not node and n.type in self.class_types):
            if sub.type in ("formal_parameter", "local_variable_declaration"):
                t = sub.child_by_field_name("type")
                if t is None or t.type not in (
                    "type_identifier",
                    "generic_type",
                    "scoped_type_identifier",
                ):
                    continue
                tname = _text(t).split("<")[0]
                if sub.type == "formal_parameter":
                    types[_text(sub.child_by_field_name("name"))] = tname
                else:
                    for decl in sub.children_by_field_name("declarator"):
                        types[_text(decl.child_by_field_name("name"))] = tname
        return dict(sorted(types.items()))

    def env_read(self, node: Node) -> EnvRead | None:
        if (
            node.type == "method_invocation"
            and _text(node.child_by_field_name("object")) == "System"
            and _text(node.child_by_field_name("name")) == "getenv"
        ):
            args = node.child_by_field_name("arguments")
            if (
                args is not None
                and args.named_children
                and args.named_children[0].type == "string_literal"
            ):
                return EnvRead(_text(args.named_children[0]).strip('"'), node.start_point[0] + 1)
        return None

    def collect_imports(self, root: Node, ctx: _Ctx) -> None:
        for node in root.named_children:
            if node.type != "import_declaration":
                continue
            text = _text(node).removeprefix("import").strip().rstrip(";").strip()
            static = text.startswith("static ")
            text = text.removeprefix("static ").strip()
            line = node.start_point[0] + 1
            if text.endswith(".*"):
                ctx.imports.append(ImportRef(text[:-2], "*", None, 0, line))
                continue
            module, _, name = text.rpartition(".")
            if static:
                ctx.imports.append(ImportRef(module, name, None, 0, line))
            else:
                ctx.imports.append(ImportRef(module, name, None, 0, line))


def parsers() -> list[BaseParser]:
    """Every tree-sitter parser whose grammar package is installed."""
    out: list[BaseParser] = []
    factories: tuple[Callable[[], BaseParser], ...] = (
        JsxAwareJavaScriptParser,
        TypeScriptDispatcher,
        GoParser,
        JavaParser,
    )
    for factory in factories:
        try:
            out.append(factory())
        except ImportError:
            continue
    return out
