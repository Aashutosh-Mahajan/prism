"""How the viewer forms its graph: folder groups, areas, and dependency tiers."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.viewer.model import ROOT_GROUP, GraphModel, area_resolver

FIXTURES = Path(__file__).parents[1] / "fixtures" / "repos"


def _indexed(name: str, tmp_path: Path) -> Path:
    root = Path(shutil.copytree(FIXTURES / name, tmp_path / name))
    apply_init(plan_init(root))
    scan(root)
    return root


def test_non_python_files_group_by_folder_not_one_package_each(tmp_path: Path) -> None:
    model = GraphModel(_indexed("polyglot", tmp_path))
    packages = {n["id"]: n for n in model.graph("import", "package").nodes}
    files = model.graph("import", "file").nodes
    # Every package holds the files of one folder; no file is promoted to a package of its own.
    assert len(packages) < len(files)
    store = [n for n in files if n["file"].startswith("svc/internal/store/")]
    assert len({n["group"] for n in store}) == 1
    group = store[0]["group"]
    assert packages[f"pkg:{group}"]["files"] == len(store)
    assert packages[f"pkg:{group}"]["dir"] == "svc/internal/store"


def test_python_package_ids_are_unchanged(tmp_path: Path) -> None:
    model = GraphModel(_indexed("small", tmp_path))
    ids = {n["id"] for n in model.graph("import", "package").nodes}
    assert {"pkg:shop", "pkg:shop.pricing", "pkg:shop.checkout"} <= ids


def test_areas_split_the_dominant_top_folder() -> None:
    files = [f"app/{d}/m{i}.py" for d in ("api", "core", "db") for i in range(5)] + [
        "tests/test_a.py",
        "setup.py",
        "src/shop/cart.py",
        "src/shop/money.py",
        "src/util/x.py",
    ]
    area = area_resolver(files)
    assert area("app/core/m1.py") == "app/core"  # 15 of 20 files: split into subfolders
    assert area("src/shop/cart.py") == "src/shop"  # a container folder is always split
    assert area("tests/test_a.py") == "tests"
    assert area("setup.py") == ROOT_GROUP
    assert area(None) == ROOT_GROUP


def test_every_node_carries_an_area(tmp_path: Path) -> None:
    model = GraphModel(_indexed("small", tmp_path))
    for level in ("package", "file", "symbol"):
        layer = "call" if level == "symbol" else "import"
        assert all(n.get("area") for n in model.graph(layer, level).nodes), level


def _edges(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"id": f"{a}->{b}", "source": a, "target": b} for a, b in pairs]


def test_tiers_run_from_foundations_up() -> None:
    tiers = GraphModel.tiers(_edges(("app", "svc"), ("svc", "db"), ("app", "db"), ("cli", "app")))
    assert tiers == {"db": 0, "svc": 1, "app": 2, "cli": 3}


def test_a_cycle_shares_one_tier() -> None:
    tiers = GraphModel.tiers(_edges(("a", "b"), ("b", "a"), ("b", "base"), ("top", "a")))
    assert tiers["a"] == tiers["b"] == 1
    assert tiers["base"] == 0 and tiers["top"] == 2
    cyclic = GraphModel.cycle_edges(_edges(("a", "b"), ("b", "a"), ("b", "base")))
    assert cyclic == {"a->b", "b->a"}


@pytest.mark.parametrize(
    ("layer", "directed"), [("import", True), ("cochange", False), ("tests", False)]
)
def test_payload_reports_tiers_only_for_directed_layers(
    tmp_path: Path, layer: str, directed: bool
) -> None:
    model = GraphModel(_indexed("small", tmp_path))
    payload = model.graph(layer, "file").to_dict()
    if directed:
        assert payload["tiers"] >= 2
        assert all("tier" in n for n in payload["nodes"])
    else:
        assert payload["tiers"] == 0
        assert all("tier" not in n for n in payload["nodes"])


def test_viewer_lookups_are_not_reported_as_agent_activity(tmp_path: Path) -> None:
    from prism.navigator import api as nav
    from prism.navigator.store import IndexStore
    from prism.viewer.api import ViewerBackend
    from prism.writers.activity import activity_path

    root = _indexed("small", tmp_path)
    log = activity_path(root)
    log.unlink(missing_ok=True)
    backend = ViewerBackend(root)
    backend.node("shop.pricing.discounts.apply_discount")
    backend.node("pkg:shop.pricing")
    backend.search({"q": "discount"})
    assert not log.exists() or not log.read_text(encoding="utf-8").strip()
    # The agent's own lookups still are.
    store = IndexStore.open(root)
    try:
        nav.op_context(store, "shop.pricing.discounts.apply_discount")
    finally:
        store.close()
    assert "apply_discount" in log.read_text(encoding="utf-8")
