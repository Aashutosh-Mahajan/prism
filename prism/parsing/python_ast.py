"""Python parser built on the stdlib `ast` module."""

from __future__ import annotations

import ast
import re

from prism.core.models import CallRef, ImportRef, ParsedFile, ParsedSymbol, SymbolKind
from prism.core.textio import decode_source
from prism.core.tokens import estimate_tokens
from prism.parsing.base_parser import BaseParser
from prism.parsing.python_facts import (
    class_fields,
    cyclomatic_complexity,
    dunder_all,
    env_reads,
    url_patterns,
)
from prism.parsing.smells import detect_smells

_DefNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _first_doc_line(node: ast.AST) -> str:
    if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return ""
    doc = ast.get_docstring(node, clean=True)
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()


def dotted_name(expr: ast.expr) -> str | None:
    """`a.b.c` -> "a.b.c"; `super().x` -> "super().x"; anything else -> None."""
    parts: list[str] = []
    node: ast.expr = expr
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "super":
        parts.append("super()")
    else:
        return None
    return ".".join(reversed(parts))


def _unparse(node: ast.AST | None) -> str:
    return "" if node is None else ast.unparse(node)


def _format_args(args: ast.arguments) -> str:
    out: list[str] = []
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults.extend(args.defaults)

    def one(arg: ast.arg, default: ast.expr | None) -> str:
        text = arg.arg
        if arg.annotation is not None:
            text += f": {_unparse(arg.annotation)}"
            if default is not None:
                text += f" = {_unparse(default)}"
        elif default is not None:
            text += f"={_unparse(default)}"
        return text

    for i, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        out.append(one(arg, default))
        if args.posonlyargs and i == len(args.posonlyargs) - 1:
            out.append("/")
    if args.vararg is not None:
        out.append("*" + one(args.vararg, None))
    elif args.kwonlyargs:
        out.append("*")
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        out.append(one(arg, kw_default))
    if args.kwarg is not None:
        out.append("**" + one(args.kwarg, None))
    return ", ".join(out)


def _signature(node: _DefNode) -> str:
    if isinstance(node, ast.ClassDef):
        bases = [_unparse(b) for b in node.bases] + [_unparse(k) for k in node.keywords]
        return f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    sig = f"{prefix}{node.name}({_format_args(node.args)})"
    if node.returns is not None:
        sig += f" -> {_unparse(node.returns)}"
    return sig


class _CallCollector(ast.NodeVisitor):
    """Collect calls in a body, descending into nested functions but not nested symbols."""

    def __init__(self) -> None:
        self.calls: list[CallRef] = []

    def visit_Call(self, node: ast.Call) -> None:
        target = dotted_name(node.func)
        if target is not None and target != "super":  # `super()` alone is plumbing, not a call edge
            self.calls.append(CallRef(target=target, line=node.lineno))
        self.generic_visit(node)


def _collect_calls(stmts: list[ast.stmt]) -> list[CallRef]:
    collector = _CallCollector()
    for stmt in stmts:
        collector.visit(stmt)
    return sorted(set(collector.calls), key=lambda c: (c.line, c.target))


def _module_statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Module-level statements, looking through `if`/`try`/`with` blocks for definitions.

    Compound blocks that contain no definitions are returned whole so their calls are kept.
    """
    out: list[ast.stmt] = []
    for stmt in body:
        if isinstance(stmt, ast.If) and _is_main_guard(stmt):
            out.append(stmt)
            continue
        blocks: list[list[ast.stmt]] = []
        if isinstance(stmt, ast.If):
            blocks = [stmt.body, stmt.orelse]
        elif isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
            try_stmt: ast.Try = stmt  # type: ignore[assignment]
            blocks = [try_stmt.body, try_stmt.orelse, try_stmt.finalbody]
            blocks.extend(h.body for h in try_stmt.handlers)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            blocks = [stmt.body]
        has_defs = any(
            isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for block in blocks
            for s in block
        )
        if not has_defs:
            out.append(stmt)
            continue
        for block in blocks:
            out.extend(_module_statements(block))
    return out


def _annotation_type(expr: ast.expr | None) -> str | None:
    """Class named by an annotation: `Cart`, `m.Cart`, `"Cart"`, `Cart | None`, `Optional[Cart]`."""
    if expr is None:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        text = expr.value.strip()
        return text if text.replace(".", "").replace("_", "").isalnum() else None
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        for side in (expr.left, expr.right):
            if not (isinstance(side, ast.Constant) and side.value is None):
                return _annotation_type(side)
        return None
    if isinstance(expr, ast.Subscript) and dotted_name(expr.value) in (
        "Optional",
        "typing.Optional",
    ):
        return _annotation_type(expr.slice)
    return dotted_name(expr)


def _local_types(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Best-effort variable types from parameter annotations and `x = Name(...)` assignments."""
    types: dict[str, str] = {}
    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        t = _annotation_type(arg.annotation)
        if t:
            types[arg.arg] = t
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
            target, value = sub.targets[0], sub.value
            if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                ctor = dotted_name(value.func)
                if ctor:
                    types.setdefault(target.id, ctor)
        elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            t = _annotation_type(sub.annotation)
            if t:
                types.setdefault(sub.target.id, t)
    types.pop("self", None)
    types.pop("cls", None)
    return dict(sorted(types.items()))


def _names_used(tree: ast.Module) -> list[str]:
    """Identifiers read anywhere in the module (names and attribute names).

    Used to avoid calling a function dead when it is passed as a callback or
    referenced as an attribute rather than called directly.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return sorted(names)


def _is_main_guard(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.If) or not isinstance(stmt.test, ast.Compare):
        return False
    test = stmt.test
    sides = [test.left, *test.comparators]
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
    return has_name and has_main and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)


_PY_LINES = re.compile(r"\r\n|\r|\n")  # how Python ends a line (not str.splitlines)


class PythonAstParser(BaseParser):
    language = "python"

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        text = decode_source(source)
        parts = _PY_LINES.split(text)
        line_count = len(parts) - (1 if parts[-1] == "" else 0)
        result = ParsedFile(
            path=path,
            language=self.language,
            module=module,
            is_package=is_package,
            line_count=line_count,
            doc="",
        )
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as exc:
            # Undecodable bytes (a stray 0xFF in a comment) must not hide a file's symbols:
            # retry on the lossy-decoded text before reporting a parse error.
            try:
                tree = ast.parse(text, filename=path)
            except (SyntaxError, ValueError):
                result.parse_error = f"{type(exc).__name__}: {exc}"
                return result

        result.doc = _first_doc_line(tree)
        result.imports = self._imports(tree)
        lines = _PY_LINES.split(text)
        module_level: list[ast.stmt] = []
        seen: dict[str, int] = {}
        for stmt in _module_statements(tree.body):
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._symbol(stmt, None, result.symbols, lines)
            else:
                module_level.append(stmt)
                if _is_main_guard(stmt):
                    result.has_main_guard = True
        # A redefined name (overloads, conditional defs) keeps its last definition,
        # which is the one in effect at runtime.
        for i, sym in enumerate(result.symbols):
            seen[sym.qualname] = i
        result.symbols = [s for i, s in enumerate(result.symbols) if seen[s.qualname] == i]
        result.module_calls = _collect_calls(module_level)
        result.module_env_reads = env_reads(module_level)
        result.url_patterns = url_patterns(module_level)
        result.all_names = dunder_all(tree)
        result.names_used = _names_used(tree)
        result.smells = detect_smells(tree, text, is_package, result.all_names)
        return result

    def _imports(self, tree: ast.Module) -> list[ImportRef]:
        refs: list[ImportRef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    refs.append(ImportRef(alias.name, None, alias.asname, 0, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    refs.append(
                        ImportRef(
                            node.module or "", alias.name, alias.asname, node.level, node.lineno
                        )
                    )
        refs.sort(key=lambda r: (r.line, r.module, r.name or "", r.alias or ""))
        return refs

    def _symbol(
        self,
        node: _DefNode,
        parent: ParsedSymbol | None,
        out: list[ParsedSymbol],
        lines: list[str],
    ) -> None:
        kind: SymbolKind
        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif parent is not None and parent.kind == "class":
            kind = "method"
        else:
            kind = "function"
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        end = node.end_lineno or node.lineno
        qualname = f"{parent.qualname}.{node.name}" if parent else node.name
        body_stmts: list[ast.stmt] = []
        nested: list[_DefNode] = []
        for stmt in node.body:
            if isinstance(node, ast.ClassDef) and isinstance(
                stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                nested.append(stmt)
            else:
                body_stmts.append(stmt)
        # Decorator calls execute at definition time; attribute them to the decorated symbol.
        extra: list[ast.stmt] = [ast.Expr(value=d) for d in node.decorator_list]
        symbol = ParsedSymbol(
            name=node.name,
            qualname=qualname,
            kind=kind,
            lines=(start, end),
            signature=_signature(node),
            doc=_first_doc_line(node),
            decorators=[_unparse(d) for d in node.decorator_list],
            bases=[b for b in (dotted_name(b) for b in node.bases) if b]
            if isinstance(node, ast.ClassDef)
            else [],
            calls=_collect_calls(extra + body_stmts),
            parent=parent.qualname if parent else None,
            tokens_est=estimate_tokens("\n".join(lines[start - 1 : end])),
            local_types={} if isinstance(node, ast.ClassDef) else _local_types(node),
            complexity=1 if isinstance(node, ast.ClassDef) else cyclomatic_complexity(node),
            fields=class_fields(node) if isinstance(node, ast.ClassDef) else [],
            env_reads=env_reads(body_stmts),
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )
        out.append(symbol)
        for child in nested:
            self._symbol(child, symbol, out, lines)
