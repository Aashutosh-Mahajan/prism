from __future__ import annotations

import textwrap

from prism.core.models import ParsedFile
from prism.parsing import get_parser, module_name


def parse(src: str, module: str = "pkg.mod", is_package: bool = False) -> ParsedFile:
    parser = get_parser("python")
    assert parser is not None
    return parser.parse("pkg/mod.py", textwrap.dedent(src).encode(), module, is_package)


def test_module_name_mapping() -> None:
    assert module_name("src/shop/pricing/__init__.py") == ("shop.pricing", True)
    assert module_name("src/shop/money.py") == ("shop.money", False)
    assert module_name("tests/test_cart.py") == ("tests.test_cart", False)
    assert module_name("lib/x.py", ("lib",)) == ("x", False)
    assert module_name("my-scripts/run.py") == ("my_scripts.run", False)
    assert module_name("__init__.py") == ("__init__", True)


def test_symbols_lines_signatures_and_docs() -> None:
    pf = parse(
        '''
        """Module doc.

        More.
        """

        @decorator(arg=1)
        def f(a: int, b: str = "x", *args: int, c: bool, **kw: object) -> int:
            """First line.

            Second line.
            """
            return a

        async def g(x, /, y=2, *, z):
            pass

        class C(Base, metaclass=Meta):
            """A class."""

            def m(self) -> None:
                pass

            class Inner:
                def deep(self):
                    pass
        '''
    )
    assert pf.parse_error is None
    assert pf.doc == "Module doc."
    by_q = {s.qualname: s for s in pf.symbols}
    assert list(by_q) == ["f", "g", "C", "C.m", "C.Inner", "C.Inner.deep"]
    f = by_q["f"]
    assert f.kind == "function"
    assert f.lines == (7, 13)  # starts at the decorator
    assert (
        f.signature
        == 'f(a: int, b: str = "x", *args: int, c: bool, **kw: object) -> int'.replace('"x"', "'x'")
    )
    assert f.doc == "First line."
    assert f.decorators == ["decorator(arg=1)"]
    assert by_q["g"].signature == "async g(x, /, y=2, *, z)"
    assert by_q["C"].signature == "class C(Base, metaclass=Meta)"
    assert by_q["C"].bases == ["Base"]
    assert by_q["C.m"].kind == "method" and by_q["C.m"].parent == "C"
    assert by_q["C.Inner"].kind == "class"
    assert by_q["C.Inner.deep"].kind == "method" and by_q["C.Inner.deep"].parent == "C.Inner"
    assert all(s.tokens_est > 0 for s in pf.symbols)


def test_calls_are_attributed_to_the_innermost_symbol() -> None:
    pf = parse(
        """
        import os

        setup()

        def outer():
            helper()
            def inner():
                nested_call()
            return self.x.y()

        class K:
            registry = build()

            def m(self):
                self.other()
                super().m()
                (lambda: 1)()
        """
    )
    by_q = {s.qualname: s for s in pf.symbols}
    assert [c.target for c in by_q["outer"].calls] == ["helper", "nested_call", "self.x.y"]
    assert [c.target for c in by_q["K"].calls] == ["build"]
    assert [c.target for c in by_q["K.m"].calls] == ["self.other", "super().m"]
    assert [c.target for c in pf.module_calls] == ["setup"]


def test_imports() -> None:
    pf = parse(
        """
        import a.b
        import c as d
        from e.f import g, h as i
        from . import j
        from ..k import *

        def lazy():
            import late
        """
    )
    got = [(r.module, r.name, r.alias, r.level, r.bound_name) for r in pf.imports]
    assert got == [
        ("a.b", None, None, 0, "a"),
        ("c", None, "d", 0, "d"),
        ("e.f", "g", None, 0, "g"),
        ("e.f", "h", "i", 0, "i"),
        ("", "j", None, 1, "j"),
        ("k", "*", None, 2, "*"),
        ("late", None, None, 0, "late"),
    ]


def test_main_guard_and_conditional_definitions() -> None:
    pf = parse(
        """
        import sys

        if sys.version_info >= (3, 11):
            def compat():
                pass
        else:
            def compat():
                pass

        try:
            from fast import speedy
        except ImportError:
            def speedy():
                pass

        if __name__ == "__main__":
            compat()
        """
    )
    assert pf.has_main_guard
    assert [s.qualname for s in pf.symbols] == ["compat", "speedy"]
    assert pf.symbols[0].lines[0] == 8  # the last definition wins
    assert [c.target for c in pf.module_calls] == ["compat"]


def test_local_types_from_annotations_and_constructors() -> None:
    pf = parse(
        """
        def f(cart: Cart, maybe: "m.Money | None", opt: Optional[Rule] = None, n: int = 0):
            session = db.Session()
            count: Counter = make()
            x = y
        """
    )
    assert pf.symbols[0].local_types == {
        "cart": "Cart",
        "count": "Counter",
        "n": "int",
        "opt": "Rule",
        "session": "db.Session",
    }


def test_syntax_error_is_recorded_not_raised() -> None:
    pf = parse("def broken(:\n    pass\n")
    assert pf.parse_error is not None and pf.parse_error.startswith("SyntaxError")
    assert pf.symbols == []


def test_non_utf8_and_bom_sources() -> None:
    parser = get_parser("python")
    assert parser is not None
    bom = parser.parse("a.py", b"\xef\xbb\xbfdef f():\n    pass\n", "a", False)
    assert [s.name for s in bom.symbols] == ["f"]
    latin = parser.parse(
        "b.py", b"# -*- coding: latin-1 -*-\ns = '\xe9'\ndef g(): pass\n", "b", False
    )
    assert [s.name for s in latin.symbols] == ["g"]
