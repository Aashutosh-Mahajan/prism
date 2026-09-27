"""Static smell detectors (CLAUDE.md 10.3). Cheap and deterministic.

Smells are *leads* for the audit plan, not findings: the host agent must
confirm each one in context before recording it. Secret detectors report
the location only, never the value.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

from prism.core.models import Smell

LONG_FUNCTION_LINES = 80
_BROAD = frozenset({"Exception", "BaseException"})
_DANGEROUS = {
    "eval": "eval()",
    "exec": "exec()",
    "pickle.loads": "pickle.loads()",
    "pickle.load": "pickle.load()",
    "marshal.loads": "marshal.loads()",
    "os.system": "os.system()",
    "os.popen": "os.popen()",
}
_SUBPROCESS = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
    }
)
_SQL_METHODS = frozenset({"execute", "executemany", "executescript", "raw", "extra"})
_SQL_WORDS = re.compile(r"\b(select|insert|update|delete|drop|create|alter)\b", re.IGNORECASE)
_SECRET_NAME = re.compile(
    r"(passw(or)?d|secret|api_?key|access_?key|private_?key|auth_?token|token)$", re.I
)
_SECRET_VALUE = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}"
)
_PLACEHOLDER = re.compile(
    r"^(|x+|\*+|changeme|change-me|your[-_ ].*|<.*>|\{.*\}|dummy|test|example.*)$", re.I
)
_TODO = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")


def _dotted(expr: ast.expr) -> str | None:
    from prism.parsing.python_ast import dotted_name

    return dotted_name(expr)


def _is_stringy_sql(arg: ast.expr) -> bool:
    """A query assembled with an f-string, `%`, `+`, or `.format()`."""
    if isinstance(arg, ast.JoinedStr):
        text = "".join(
            v.value for v in arg.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
        return any(isinstance(v, ast.FormattedValue) for v in arg.values) and bool(
            _SQL_WORDS.search(text)
        )
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Mod, ast.Add)):
        return any(
            isinstance(side, ast.Constant)
            and isinstance(side.value, str)
            and _SQL_WORDS.search(side.value)
            for side in (arg.left, arg.right)
        )
    if (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Attribute)
        and arg.func.attr == "format"
    ):
        base = arg.func.value
        return (
            isinstance(base, ast.Constant)
            and isinstance(base.value, str)
            and bool(_SQL_WORDS.search(base.value))
        )
    return False


def _swallows(handler: ast.ExceptHandler) -> bool:
    return all(
        isinstance(s, (ast.Pass, ast.Continue))
        or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        for s in handler.body
    )


def _unreachable(body: list[ast.stmt], out: list[Smell]) -> None:
    for i, stmt in enumerate(body[:-1]):
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            nxt = body[i + 1]
            out.append(
                Smell(
                    "unreachable_code",
                    nxt.lineno,
                    f"statement after `{type(stmt).__name__.lower()}`",
                )
            )
            break


class _Visitor(ast.NodeVisitor):
    def __init__(self, async_names: set[str]) -> None:
        self.out: list[Smell] = []
        self.async_names = async_names
        self._in_async = 0

    def generic_visit(self, node: ast.AST) -> None:
        for fld in ("body", "orelse", "finalbody"):
            body = getattr(node, fld, None)
            if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
                _unreachable(body, self.out)
        super().generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.out.append(Smell("bare_except", node.lineno, "bare `except:`"))
        elif isinstance(node.type, ast.Name) and node.type.id in _BROAD:
            self.out.append(Smell("broad_except", node.lineno, f"`except {node.type.id}`"))
        if _swallows(node):
            self.out.append(Smell("swallowed_exception", node.lineno, "exception silently ignored"))
        self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]
        for d in defaults:
            mutable = isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(d, ast.Call) and _dotted(d.func) in ("list", "dict", "set")
            )
            if mutable:
                self.out.append(
                    Smell("mutable_default", d.lineno, f"mutable default argument in `{node.name}`")
                )
        length = (node.end_lineno or node.lineno) - node.lineno + 1
        if length > LONG_FUNCTION_LINES:
            self.out.append(Smell("long_function", node.lineno, f"`{node.name}` is {length} lines"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)
        self._in_async += 1
        self.generic_visit(node)
        self._in_async -= 1

    def visit_Expr(self, node: ast.Expr) -> None:
        # A bare call to a coroutine function inside async code: likely a missing `await`.
        if self._in_async and isinstance(node.value, ast.Call):
            name = _dotted(node.value.func) or ""
            leaf = name.split(".")[-1]
            if name in self.async_names or (
                name.startswith(("self.", "cls.")) and leaf in self.async_names
            ):
                self.out.append(
                    Smell("missing_await", node.lineno, f"`{name}()` is async but not awaited")
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func) or ""
        if name in _DANGEROUS:
            self.out.append(Smell("dangerous_call", node.lineno, _DANGEROUS[name]))
        elif (
            name == "yaml.load"
            and not any(k.arg == "Loader" for k in node.keywords)
            and len(node.args) < 2
        ):
            self.out.append(
                Smell("dangerous_call", node.lineno, "yaml.load() without a safe Loader")
            )
        elif name in _SUBPROCESS and any(
            k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in node.keywords
        ):
            self.out.append(Smell("dangerous_call", node.lineno, f"{name}(shell=True)"))
        leaf = name.rsplit(".", 1)[-1]
        if leaf in _SQL_METHODS and node.args and _is_stringy_sql(node.args[0]):
            self.out.append(
                Smell(
                    "sql_string_formatting",
                    node.lineno,
                    f"query built by string formatting in `{leaf}()`",
                )
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = node.value
        if (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and len(value.value) >= 8
        ):
            for target in node.targets:
                name = (
                    target.id
                    if isinstance(target, ast.Name)
                    else (target.attr if isinstance(target, ast.Attribute) else "")
                )
                if (
                    name
                    and _SECRET_NAME.search(name)
                    and not _PLACEHOLDER.match(value.value.strip())
                ):
                    self.out.append(
                        Smell(
                            "hardcoded_secret", node.lineno, f"string literal assigned to `{name}`"
                        )
                    )
                    break
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _SECRET_VALUE.search(node.value):
            self.out.append(
                Smell("hardcoded_secret", node.lineno, "string matches a known credential format")
            )


def _todos(source: str) -> list[Smell]:
    out: list[Smell] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                m = _TODO.search(tok.string)
                if m:
                    out.append(Smell("todo", tok.start[0], tok.string.lstrip("# ").strip()[:120]))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        pass
    return out


def _unused_imports(tree: ast.Module, all_names: list[str] | None) -> list[Smell]:
    bound: dict[str, int] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for a in stmt.names:
                bound[a.asname or a.name.split(".")[0]] = stmt.lineno
        elif isinstance(stmt, ast.ImportFrom) and stmt.module != "__future__":
            for a in stmt.names:
                if a.name != "*":
                    bound[a.asname or a.name] = stmt.lineno
    if not bound:
        return []
    used: set[str] = set(all_names or [])
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif (
            isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200
        ):
            used.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value))  # string annotations
    return [
        Smell("unused_import", line, f"`{name}` is imported but never used")
        for name, line in sorted(bound.items(), key=lambda x: (x[1], x[0]))
        if name not in used and not name.startswith("_")
    ]


def detect_smells(
    tree: ast.Module, source: str, is_package: bool, all_names: list[str] | None
) -> list[Smell]:
    async_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    visitor = _Visitor(async_names)
    visitor.visit(tree)
    smells = visitor.out + _todos(source)
    if not is_package:  # package __init__ files import to re-export
        smells += _unused_imports(tree, all_names)
    return sorted(set(smells), key=lambda s: (s.line, s.kind, s.detail))
