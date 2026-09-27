"""JS/TS/Go/Java via the optional tree-sitter extra (skipped when it isn't installed)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")
pytest.importorskip("tree_sitter_go")
pytest.importorskip("tree_sitter_java")

from prism.core.models import Index
from prism.parsing.modules import module_name
from prism.parsing.treesitter import resolve_js_specifier
from prism.pipeline import build_index

FIXTURE = Path(__file__).parents[1] / "fixtures" / "repos" / "polyglot"


@pytest.fixture(scope="module")
def index() -> Iterator[Index]:
    yield build_index(FIXTURE)


def edges(index: Index) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in index.call_graph.edges}


def test_module_names_and_specifiers() -> None:
    assert module_name("src/web/components/index.ts", language="typescript") == (
        "web.components",
        True,
    )
    assert module_name("web/tests/cart.test.ts", language="typescript") == (
        "web.tests.cart_test",
        False,
    )
    assert module_name("svc/internal/store/store.go", language="go") == (
        "svc.internal.store.store",
        False,
    )
    assert module_name("pkg/index.py") == ("pkg.index", False)  # `index` is only special in JS/TS
    assert resolve_js_specifier("web.src.cart", True, "../util/money") == "web.src.util.money"
    assert resolve_js_specifier("web.src.app", False, "./cart/index.js") == "web.src.cart"
    assert resolve_js_specifier("web.src.app", False, "@/lib/api") == "lib.api"
    assert resolve_js_specifier("web.src.app", False, "lodash/fp") == "lodash.fp"


def test_all_languages_parse(index: Index) -> None:
    assert index.languages == {"java": 3, "go": 4, "javascript": 1, "typescript": 3}
    assert not [p for p in index.parsed if p.parse_error]


def test_typescript(index: Index) -> None:
    cart = index.symbols["web.src.cart.Cart"]
    assert cart.kind == "class" and cart.doc == "A shopping cart."
    total = index.symbols["web.src.cart.Cart.total"]
    assert total.signature == "total(discount: number) -> Money"
    checkout = index.symbols["web.src.cart.checkout"]
    assert checkout.kind == "function" and checkout.signature == "checkout(cart: Cart) -> number"
    got = edges(index)
    assert ("web.src.cart.Cart.total", "web.src.util.money.zero") in got
    assert (
        "web.src.cart.checkout",
        "web.src.cart.Cart.total",
    ) in got  # via the `cart: Cart` annotation
    assert ("web.src.app.main", "web.src.cart.checkout") in got  # require() destructuring
    assert index.tests_map.by_symbol["web.src.cart.Cart"] == ["web/tests/cart.test.ts"]
    assert "lodash" in index.import_graph.external


def test_go(index: Index) -> None:
    save = index.symbols["svc.internal.store.store.Store.Save"]
    assert save.kind == "method" and save.visibility == "public"
    assert index.symbols["svc.internal.store.validate.validate"].visibility == "private"
    got = edges(index)
    # Same-package call across files, and an imported package function.
    assert ("svc.internal.store.store.Store.Save", "svc.internal.store.validate.validate") in got
    assert ("svc.cmd.server.main.main", "svc.internal.store.store.New") in got
    imports = {(e.source, e.target) for e in index.import_graph.edges}
    assert ("svc.cmd.server.main", "svc.internal.store.store") in imports
    assert ("svc.cmd.server.main", "svc.internal.store.store_test") not in imports
    assert index.tests_map.by_symbol["svc.internal.store.store.New"] == [
        "svc/internal/store/store_test.go"
    ]
    keys = {k.key: k for k in index.config}
    assert keys["STORE_DSN"].reads[0].symbol == "svc.internal.store.store.New"


def test_java(index: Index) -> None:
    assert "com.acme.shop.Cart" in index.import_graph.modules  # module from the package declaration
    got = edges(index)
    assert ("com.acme.shop.Cart.Cart.total", "com.acme.shop.Money.Money.plus") in got
    assert (
        "com.acme.shop.Cart.Cart.main",
        "com.acme.shop.Money.Money",
    ) in got  # same package, no import
    kinds = {(ep.kind, ep.symbol) for ep in index.entry_points}
    assert ("main_function", "com.acme.shop.Cart.Cart.main") in kinds
    assert index.tests_map.by_symbol["com.acme.shop.Cart.Cart.total"] == [
        "jvm/src/test/java/com/acme/shop/CartTest.java"
    ]
    assert index.symbols["com.acme.shop.Money.Money"].doc == "Money in cents."


def test_complexity_and_todo_smells(index: Index) -> None:
    total = next(
        ps
        for pf in index.parsed
        for ps in pf.symbols
        if pf.module == "web.src.cart" and ps.qualname == "Cart.total"
    )
    assert total.complexity >= 4  # for + if + &&
    app = next(pf for pf in index.parsed if pf.path == "web/src/app.js")
    assert any(s.kind == "todo" for s in app.smells)
    assert index.symbols["web.src.app.main"].doc == ""  # a TODO comment is not a docstring
