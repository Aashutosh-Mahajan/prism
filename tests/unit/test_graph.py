from __future__ import annotations

import textwrap

from prism.core.models import ParsedFile
from prism.graph import build_call_graph, build_import_graph, build_symbol_table, pagerank
from prism.graph.symbol_table import SymbolTable, resolve_relative, visibility_for
from prism.parsing import get_parser, module_name


def make_table(files: dict[str, str]) -> SymbolTable:
    parser = get_parser("python")
    assert parser is not None
    parsed: list[ParsedFile] = []
    for path, src in files.items():
        mod, is_pkg = module_name(path)
        parsed.append(parser.parse(path, textwrap.dedent(src).encode(), mod, is_pkg))
    return build_symbol_table(parsed)


def edges(files: dict[str, str]) -> dict[tuple[str, str], str]:
    table = make_table(files)
    graph = build_call_graph(table)
    return {(e.source, e.target): e.confidence for e in graph.edges}


def test_visibility() -> None:
    assert visibility_for("pkg.mod", "f") == "public"
    assert visibility_for("pkg.mod", "_f") == "private"
    assert visibility_for("pkg._internal", "f") == "private"
    assert visibility_for("pkg.mod", "C.__init__") == "public"
    assert visibility_for("pkg.mod", "C._helper") == "private"


def test_resolve_relative() -> None:
    from prism.core.models import ImportRef

    assert resolve_relative("a.b.c", False, ImportRef("x", "y", None, 1, 1)) == "a.b.x"
    assert resolve_relative("a.b", True, ImportRef("x", "y", None, 1, 1)) == "a.b.x"
    assert resolve_relative("a.b.c", False, ImportRef("", "y", None, 2, 1)) == "a"
    assert resolve_relative("a.b.c", False, ImportRef("abs", None, None, 0, 1)) == "abs"


def test_import_graph_internal_external_and_relative() -> None:
    table = make_table(
        {
            "pkg/__init__.py": "from .core import run\n",
            "pkg/core.py": "import os\nimport requests\nfrom pkg import util\n",
            "pkg/util.py": "from . import core\nimport numpy.linalg as la\n",
            "pkg/sub/__init__.py": "",
            "pkg/sub/deep.py": "from ..util import thing\nimport pkg.sub\n",
        }
    )
    graph = build_import_graph(table)
    got = {(e.source, e.target) for e in graph.edges}
    assert got == {
        ("pkg", "pkg.core"),
        ("pkg.core", "pkg.util"),
        ("pkg.util", "pkg.core"),
        ("pkg.sub.deep", "pkg.util"),
        ("pkg.sub.deep", "pkg.sub"),
    }
    assert graph.external == {"numpy": 1, "requests": 1}  # stdlib excluded
    assert graph.modules["pkg.util"].imported_by == ["pkg.core", "pkg.sub.deep"]
    assert sum(m.rank for m in graph.modules.values()) > 0.99


def test_import_graph_suffix_fallback_for_nested_roots() -> None:
    table = make_table(
        {
            "backend/app/__init__.py": "",
            "backend/app/main.py": "from app.models import User\n",
            "backend/app/models.py": "class User: pass\n",
        }
    )
    got = {(e.source, e.target) for e in build_import_graph(table).edges}
    assert ("backend.app.main", "backend.app.models") in got


def test_call_resolution_kinds() -> None:
    got = edges(
        {
            "pkg/__init__.py": "from .impl import exported\n",
            "pkg/impl.py": """
                def exported():
                    return helper()

                def helper():
                    return 1
            """,
            "pkg/models.py": """
                class Base:
                    def save(self):
                        pass
                    def validate(self):
                        pass

                class User(Base):
                    def save(self):
                        self.validate()
                        super().save()
                        return self.name()

                    def name(self):
                        return "x"
            """,
            "pkg/service.py": """
                import pkg
                from pkg import models as m
                from pkg.models import User

                def create(u: User):
                    u.save()
                    fresh = m.User()
                    fresh.validate()
                    pkg.exported()
                    len([])
                    unknown_thing()
                    obj.unique_method_name()
                    obj.save()

                class Other:
                    def unique_method_name(self):
                        pass
            """,
        }
    )
    assert got[("pkg.impl.exported", "pkg.impl.helper")] == "high"
    assert got[("pkg.models.User.save", "pkg.models.Base.validate")] == "medium"
    assert got[("pkg.models.User.save", "pkg.models.Base.save")] == "medium"
    assert got[("pkg.models.User.save", "pkg.models.User.name")] == "high"
    assert got[("pkg.service.create", "pkg.models.User.save")] == "medium"
    assert got[("pkg.service.create", "pkg.models.User")] == "high"
    assert got[("pkg.service.create", "pkg.models.Base.validate")] == "medium"
    assert got[("pkg.service.create", "pkg.impl.exported")] == "high"  # via package re-export
    assert got[("pkg.service.create", "pkg.service.Other.unique_method_name")] == "low"
    targets = {t for (s, t) in got if s == "pkg.service.create"}
    assert "pkg.models.Base.save" not in targets  # obj.save is ambiguous -> dropped


def test_star_import_resolution_and_calls_backfilled() -> None:
    table = make_table(
        {
            "lib/__init__.py": "",
            "lib/tools.py": "def tool():\n    pass\n",
            "lib/use.py": "from lib.tools import *\n\ndef go():\n    tool()\n",
        }
    )
    build_call_graph(table)
    assert table.symbols["lib.use.go"].calls == ["lib.tools.tool"]
    assert table.symbols["lib.tools.tool"].called_by == ["lib.use.go"]


def test_self_recursion_is_not_an_edge() -> None:
    got = edges({"m.py": "def f(n):\n    return f(n - 1)\n"})
    assert got == {}


def test_pagerank_properties() -> None:
    assert pagerank([], []) == {}
    ranks = pagerank(["a", "b", "c"], [("a", "c"), ("b", "c")])
    assert ranks["c"] > ranks["a"] == ranks["b"]
    assert abs(sum(ranks.values()) - 1.0) < 1e-4
    # Order of inputs never changes the result.
    assert ranks == pagerank(["c", "b", "a"], [("b", "c"), ("a", "c")])
    # Unknown nodes and self-loops are ignored.
    assert pagerank(["a"], [("a", "a"), ("a", "zzz")]) == {"a": 1.0}
