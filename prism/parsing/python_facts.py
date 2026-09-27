"""Extra per-symbol facts from the Python AST: complexity, class fields, config reads,
Django URL patterns, and `__all__`."""

from __future__ import annotations

import ast

from prism.core.models import EnvRead, UrlPattern

_ENV_GETTERS = frozenset(
    {
        "os.environ.get",
        "os.getenv",
        "environ.get",
        "getenv",
        "os.environ.setdefault",
        "environ.setdefault",
    }
)
_ENV_MAPPINGS = frozenset({"os.environ", "environ"})
_URL_FUNCS = frozenset({"path", "re_path", "url", "django.urls.path", "urls.path"})


def _dotted(expr: ast.expr) -> str | None:
    from prism.parsing.python_ast import dotted_name

    return dotted_name(expr)


def cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe-style: 1 + decision points (branches, loops, handlers, boolean operators)."""
    score = 1
    for sub in ast.walk(node):
        if isinstance(
            sub, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler)
        ):
            score += 1
        elif isinstance(sub, ast.BoolOp):
            score += len(sub.values) - 1
        elif isinstance(sub, ast.comprehension):
            score += 1 + len(sub.ifs)
        elif type(sub).__name__ == "match_case":
            score += 1
    return score


def class_fields(node: ast.ClassDef) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.append((stmt.target.id, ast.unparse(stmt.annotation)))
        elif (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            name = stmt.targets[0].id
            if name.startswith("__"):
                continue
            value = stmt.value
            kind = _dotted(value.func) if isinstance(value, ast.Call) else None
            fields.append((name, kind or type(value).__name__.lower()))
    return fields


def env_reads(nodes: list[ast.stmt] | ast.AST) -> list[EnvRead]:
    reads: set[EnvRead] = set()
    roots: list[ast.AST] = list(nodes) if isinstance(nodes, list) else [nodes]
    for root in roots:
        for sub in ast.walk(root):
            if isinstance(sub, ast.Call) and sub.args:
                name = _dotted(sub.func)
                first = sub.args[0]
                if (
                    name in _ENV_GETTERS
                    and isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                ):
                    reads.add(EnvRead(first.value, sub.lineno))
            elif isinstance(sub, ast.Subscript) and _dotted(sub.value) in _ENV_MAPPINGS:
                key = sub.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    reads.add(EnvRead(key.value, sub.lineno))
    return sorted(reads, key=lambda r: (r.line, r.key))


def url_patterns(stmts: list[ast.stmt]) -> list[UrlPattern]:
    out: list[UrlPattern] = []
    for stmt in stmts:
        for sub in ast.walk(stmt):
            if not (
                isinstance(sub, ast.Call) and _dotted(sub.func) in _URL_FUNCS and len(sub.args) >= 2
            ):
                continue
            pattern, view = sub.args[0], sub.args[1]
            if not (isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)):
                continue
            if isinstance(view, ast.Call):  # `views.OrderView.as_view()`
                inner = _dotted(view.func)
                view_name = (
                    inner.rsplit(".as_view", 1)[0] if inner and inner.endswith(".as_view") else None
                )
            else:
                view_name = _dotted(view)
            if view_name and not view_name.startswith("include"):
                out.append(UrlPattern(pattern.value, view_name, sub.lineno))
    return out


def dunder_all(tree: ast.Module) -> list[str] | None:
    for stmt in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets) and isinstance(
            value, (ast.List, ast.Tuple)
        ):
            return [
                e.value
                for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    return None
