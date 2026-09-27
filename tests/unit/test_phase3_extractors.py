from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from prism.extractors.routes import parse_route_decorator
from prism.health import collect_git, read_coverage
from prism.pipeline import build_index


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("decorator", "expected"),
    [
        ('app.route("/orders", methods=["POST", "get"])', (["GET", "POST"], "/orders")),
        ('app.route("/health")', (["GET"], "/health")),
        ('router.delete("/items/{id}")', (["DELETE"], "/items/{id}")),
        ('bp.get(path="/x")', (["GET"], "/x")),
        ("app.websocket('/ws')", (["WS"], "/ws")),
        ("staticmethod", None),
        ("pytest.fixture()", None),
        ("app.get(PATH)", None),
    ],
)
def test_parse_route_decorator(decorator: str, expected: object) -> None:
    assert parse_route_decorator(decorator) == expected


def test_routes_models_config(tmp_path: Path) -> None:
    root = write(
        tmp_path,
        {
            "web/__init__.py": "",
            "web/api.py": """
                import os
                from fastapi import FastAPI
                from pydantic import BaseModel

                app = FastAPI()
                DEBUG = os.getenv("APP_DEBUG", "0")

                class Item(BaseModel):
                    name: str
                    price: float

                @app.post("/items")
                def create_item(item: Item) -> Item:
                    key = os.environ["API_TOKEN"]
                    return Item(name=key, price=1.0)
            """,
            "shop/__init__.py": "",
            "shop/models.py": """
                from django.db import models

                class Order(models.Model):
                    total = models.IntegerField()

                class RushOrder(Order):
                    pass
            """,
            "shop/views.py": """
                def order_list(request):
                    return None
            """,
            "shop/urls.py": """
                from django.urls import path
                from shop import views

                urlpatterns = [path("orders/", views.order_list)]
            """,
        },
    )
    index = build_index(root)
    routes = {(r.method, r.path, r.handler, r.framework) for r in index.routes}
    assert routes == {
        ("POST", "/items", "web.api.create_item", "fastapi"),
        ("ANY", "/orders/", "shop.views.order_list", "django"),
    }
    models = {m.id: m for m in index.models}
    assert models["web.api.Item"].framework == "pydantic"
    assert models["web.api.Item"].fields == [("name", "str"), ("price", "float")]
    assert models["web.api.Item"].used_by == ["web.api.create_item"]
    assert models["shop.models.Order"].framework == "django"
    assert models["shop.models.RushOrder"].framework == "django"  # subclass of a model
    keys = {k.key: k for k in index.config}
    assert set(keys) == {"APP_DEBUG", "API_TOKEN"}
    assert keys["API_TOKEN"].reads[0].symbol == "web.api.create_item"
    assert keys["APP_DEBUG"].reads[0].symbol is None


def test_dead_code_candidates(tmp_path: Path) -> None:
    root = write(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": """
                import functools

                __all__ = ["exported"]

                def used():
                    return 1

                def caller():
                    return used() + sorted([1], key=callback)[0]

                def callback(x):
                    return x

                def _orphan():
                    return 2

                def public_orphan():
                    return 3

                def exported():
                    return 4

                @functools.cache
                def registered():
                    return 5
            """,
            "tests/test_core.py": """
                def test_something():
                    pass
            """,
        },
    )
    dead = {d.id: d for d in build_index(root).dead_code}
    assert dead["pkg.core._orphan"].confidence == "likely"
    assert dead["pkg.core.public_orphan"].confidence == "possible"
    for alive in ("pkg.core.used", "pkg.core.callback", "pkg.core.exported", "pkg.core.registered"):
        assert alive not in dead
    assert not any(k.startswith("tests.") for k in dead)


def test_blast_radius_and_health(small_repo: Path) -> None:
    index = build_index(small_repo)
    assert index.blast is not None
    count, top = index.blast.symbols["shop.money.Money"]
    assert count >= 4 and "src/shop/pricing/discounts.py" in top
    count, _ = index.blast.files["src/shop/config.py"]
    assert count >= 2
    assert index.health is not None
    orders = index.health.files["src/shop/api/orders.py"]
    assert 0.0 <= float(orders["risk"]) <= 1.0  # type: ignore[arg-type]
    session = index.health.files["src/shop/db/session.py"]
    assert "no mapped tests" in session["reasons"]  # type: ignore[operator]
    assert index.git is not None and not index.git.available  # fixture copy is not a git repo


def test_smells_are_attributed_to_symbols(tmp_path: Path) -> None:
    root = write(
        tmp_path,
        {"m.py": "def risky(x=[]):\n    try:\n        return eval(x)\n    except:\n        pass\n"},
    )
    index = build_index(root)
    assert index.health is not None
    smells = index.health.files["m.py"]["smells"]
    kinds = {(s["kind"], s["symbol"]) for s in smells}  # type: ignore[attr-defined, index]
    assert ("dangerous_call", "m.risky") in kinds and ("bare_except", "m.risky") in kinds


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_git_intelligence(tmp_path: Path) -> None:
    root = write(tmp_path, {"a.py": "x = 1\n", "b.py": "y = 1\n", "c.py": "z = 1\n"})
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    for i in range(3):
        (root / "a.py").write_text(f"x = {i + 2}\n")
        (root / "b.py").write_text(f"y = {i + 2}\n")
        _git(root, "commit", "-qam", f"change {i}")
    git = collect_git(root, {"a.py", "b.py", "c.py"})
    assert git.available and git.commits_analyzed == 4
    assert git.churn == {"a.py": 4, "b.py": 4, "c.py": 1}
    assert git.owners["a.py"] == [("Ada", 4)]
    assert git.co_change == [("a.py", "b.py", 4, 1.0)]
    assert collect_git(root, {"a.py"}, git) is git  # HEAD unchanged -> reused


def test_coverage_reports(tmp_path: Path) -> None:
    (tmp_path / "coverage.xml").write_text(
        "<coverage><packages><package><classes>"
        '<class filename="pkg/core.py" line-rate="0.25"/><class filename="other.py" line-rate="1"/>'
        "</classes></package></packages></coverage>"
    )
    assert read_coverage(tmp_path, {"src/pkg/core.py", "x.py"}) == {"src/pkg/core.py": 0.25}
    (tmp_path / "coverage.xml").unlink()
    (tmp_path / "coverage.json").write_text(
        '{"files": {"x.py": {"summary": {"percent_covered": 80.0}}}}'
    )
    assert read_coverage(tmp_path, {"x.py"}) == {"x.py": 0.8}
