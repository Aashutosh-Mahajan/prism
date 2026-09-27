"""HTTP routes -> handler symbols: Flask/FastAPI decorators and Django URL patterns."""

from __future__ import annotations

import ast

from prism.core.models import Route
from prism.extractors.base import Extractor, ExtractorContext
from prism.graph.call_graph import Resolver

_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_ROUTE_ATTRS = frozenset({"route", "api_route", "websocket", *_VERBS})


def _const_str(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _methods_kw(call: ast.Call) -> list[str] | None:
    for kw in call.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
            vals = [_const_str(e) for e in kw.value.elts]
            return sorted({v.upper() for v in vals if v})
    return None


def parse_route_decorator(decorator: str) -> tuple[list[str], str] | None:
    """`app.post("/orders")` -> (["POST"], "/orders"); None if not a route decorator."""
    try:
        expr = ast.parse(decorator, mode="eval").body
    except SyntaxError:
        return None
    if not (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)):
        return None
    attr = expr.func.attr
    if attr not in _ROUTE_ATTRS:
        return None
    path = _const_str(expr.args[0]) if expr.args else None
    if path is None:
        for kw in expr.keywords:
            if kw.arg in ("path", "rule"):
                path = _const_str(kw.value)
    if path is None:
        return None
    if attr in _VERBS:
        methods = [attr.upper()]
    elif attr == "websocket":
        methods = ["WS"]
    else:
        methods = _methods_kw(expr) or ["GET"]
    return methods, path


class RoutesExtractor(Extractor[list[Route]]):
    name = "routes"

    def run(self, ctx: ExtractorContext) -> list[Route]:
        table = ctx.table
        routes: set[Route] = set()
        for mod, pf in table.files.items():
            externals = set(ctx.import_graph.modules[mod].external)
            framework = (
                "fastapi"
                if "fastapi" in externals
                else ("flask" if "flask" in externals else "python")
            )
            for ps in pf.symbols:
                for dec in ps.decorators:
                    parsed = parse_route_decorator(dec)
                    if parsed is None:
                        continue
                    methods, path = parsed
                    for method in methods:
                        routes.add(
                            Route(
                                method,
                                path,
                                f"{mod}.{ps.qualname}",
                                pf.path,
                                ps.lines[0],
                                framework,
                            )
                        )
        resolver: Resolver | None = None
        for mod, pf in table.files.items():
            for up in pf.url_patterns:
                resolver = resolver or Resolver(table)
                handler = resolver.resolve_name(mod, up.view)
                if handler is None:
                    continue
                path = up.pattern if up.pattern.startswith("/") else "/" + up.pattern
                routes.add(Route("ANY", path, handler, pf.path, up.line, "django"))
        return sorted(routes, key=lambda r: (r.path, r.method, r.handler))
