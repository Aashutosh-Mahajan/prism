from __future__ import annotations

from pathlib import Path

from prism.extractors.project import detect_commands
from prism.extractors.tests_map import is_test_file
from prism.pipeline import build_index


def test_is_test_file() -> None:
    dirs = ("tests", "test")
    assert is_test_file("tests/test_x.py", dirs)
    assert is_test_file("src/pkg/x_test.py", dirs)
    assert is_test_file("tests/helpers/factory.py", dirs)
    assert is_test_file("conftest.py", dirs)
    assert not is_test_file("src/pkg/testing.py", dirs)
    assert not is_test_file("src/contest.py", dirs)


def test_entry_points_on_tiny(tiny_repo: Path) -> None:
    eps = build_index(tiny_repo).entry_points
    got = {(e.kind, e.module, e.symbol, e.name) for e in eps}
    assert got == {
        ("console_script", "tinyshop.cli", "tinyshop.cli.main", "tinyshop"),
        ("main_guard", "tinyshop.cli", "tinyshop.cli.main", None),
    }


def test_entry_points_on_small(small_repo: Path) -> None:
    index = build_index(small_repo)
    got = {(e.kind, e.module, e.symbol) for e in index.entry_points}
    assert ("console_script", "shop.api.app", "shop.api.app.run") in got
    assert ("main_guard", "shop.api.app", "shop.api.app.run") in got
    assert ("main_function", "scripts.seed", "scripts.seed.main") in got
    assert index.import_graph.modules["shop.api.app"].entry_point == "console_script"


def test_dunder_main(tmp_path: Path) -> None:
    (tmp_path / "tool").mkdir()
    (tmp_path / "tool" / "__init__.py").write_text("")
    (tmp_path / "tool" / "__main__.py").write_text("def main():\n    pass\n\nmain()\n")
    eps = build_index(tmp_path).entry_points
    assert ("dunder_main", "tool.__main__", "tool.__main__.main") in {
        (e.kind, e.module, e.symbol) for e in eps
    }


def test_tests_map_on_small(small_repo: Path) -> None:
    tm = build_index(small_repo).tests_map
    assert tm.test_files == [
        "tests/test_cart.py",
        "tests/test_discounts.py",
        "tests/test_orders.py",
    ]
    assert tm.by_symbol["shop.pricing.discounts.apply_discount"] == ["tests/test_discounts.py"]
    assert tm.by_symbol["shop.checkout.cart.Cart.total"] == ["tests/test_cart.py"]
    assert tm.by_file["src/shop/checkout/cart.py"] == ["tests/test_cart.py"]
    # Naming convention: test_discounts.py -> discounts.py
    assert "tests/test_discounts.py" in tm.by_file["src/shop/pricing/discounts.py"]
    assert not any(k.startswith("tests.") for k in tm.by_symbol)


def test_detect_commands(tmp_path: Path) -> None:
    assert detect_commands(tmp_path, has_tests=False) == {}
    assert detect_commands(tmp_path, has_tests=True) == {"test": "python -m pytest -q"}
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ruff]\n[tool.mypy]\n[tool.pytest.ini_options]\n"
    )
    assert detect_commands(tmp_path, has_tests=False) == {
        "lint": "ruff check .",
        "test": "python -m pytest -q",
        "typecheck": "python -m mypy .",
    }


def test_detect_commands_in_a_django_and_react_monorepo(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend" / "app"
    backend.mkdir()
    frontend.mkdir(parents=True)
    (backend / "manage.py").write_text("import django\n")
    (backend / "requirements.txt").write_text("django\n")
    (frontend / "package.json").write_text(
        '{"scripts": {"lint": "eslint ."}, "devDependencies": {"vitest": "^1"}}'
    )
    (tmp_path / "frontend" / "app" / "node_modules").mkdir()
    (tmp_path / "frontend" / "app" / "node_modules" / "package.json").write_text("{}")
    assert detect_commands(tmp_path, has_tests=True) == {
        "test (backend)": "cd backend && python manage.py test",
        "test (frontend/app)": "cd frontend/app && npx vitest run",
        "lint (frontend/app)": "cd frontend/app && npm run lint",
    }


def test_http_requests_in_tests_link_to_route_handlers() -> None:
    from prism.core.models import Route
    from prism.extractors.tests_map import routes_requested

    routes = [
        Route("ANY", "/auth/login/", "app.views.LoginView", "app/urls.py", 3, "django"),
        Route("ANY", "/orders/<int:pk>/", "app.views.OrderDetail", "app/urls.py", 4, "django"),
        Route("POST", "/orders", "api.create_order", "api.py", 9, "fastapi"),
        Route("GET", "/orders", "api.list_orders", "api.py", 5, "fastapi"),
    ]
    source = (
        'self.client.post("/api/v1/auth/login/")\n'
        "client.get(f'/api/orders/{order.pk}/')\n"
        "await request(app).post(`/orders`)\n"
        'client.get("/unrelated/")\n'
    )
    assert routes_requested(source, routes) == {
        "app.views.LoginView",  # mounted under a prefix the route does not record
        "api.create_order",  # the verb picks POST over GET
        "api.list_orders",  # f-string: `/api/orders/` is the GET /orders suffix
    }
    assert routes_requested('client.get("/api/orders/7/")', routes) == {"app.views.OrderDetail"}


def test_reverse_names_link_tests_to_views() -> None:
    from prism.extractors.tests_map import url_names_requested

    names = {"send-otp": {"accounts.views.SendOTPView"}, "detail": {"a.D", "b.D", "c.D", "d.D"}}
    source = 'client.post(reverse("send-otp"))\nreverse("accounts:detail")\nreverse("missing")'
    assert url_names_requested(source, names) == {"accounts.views.SendOTPView"}


def test_django_test_urls_and_names_reach_the_tests_map(tmp_path: Path) -> None:
    app = tmp_path / "shop"
    (app / "tests").mkdir(parents=True)
    (tmp_path / "other").mkdir()
    for directory in (app, app / "tests", tmp_path / "other"):
        (directory / "__init__.py").write_text("")
    (app / "views.py").write_text("class Login:\n    pass\n\n\ndef card(request):\n    pass\n")
    (tmp_path / "other" / "views.py").write_text("def unrelated():\n    pass\n")
    (app / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n\nurlpatterns = [\n"
        '    path("login/", views.Login.as_view()),\n'
        '    path("card/", views.card, name="health-card"),\n]\n'
    )
    (app / "tests" / "test_views.py").write_text(
        "def test_login(client):\n    client.post('/api/shop/login/')\n\n\n"
        "def test_card(client):\n    client.get(reverse('health-card'))\n"
    )
    index = build_index(tmp_path)
    tests = "shop/tests/test_views.py"
    assert tests in index.tests_map.by_symbol["shop.views.Login"]
    assert tests in index.tests_map.by_symbol["shop.views.card"]
    assert "other/views.py" not in index.tests_map.by_file  # same app wins the name match
