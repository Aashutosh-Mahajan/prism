from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from prism.core.errors import AmbiguousTargetError, IndexMissingError, NotFoundError
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import api, render
from prism.navigator.store import IndexStore
from prism.navigator.text import stem, tokenize
from prism.writers.activity import read_activity
from prism.writers.agents_md import BRIEF_TOKEN_LIMIT


@pytest.fixture
def store(small_repo: Path) -> Iterator[IndexStore]:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    st = IndexStore.open(small_repo)
    yield st
    st.close()


def test_tokenize_splits_identifiers() -> None:
    toks = tokenize("applyDiscount apply_discount HTTPServer the")
    assert {
        stem("apply"),
        "discount",
        "apply_discount",
        "http",
        stem("server"),
        "applydiscount",
    } <= set(toks)
    assert "the" not in toks


def test_search_terms_are_stemmed_consistently() -> None:
    # A bug report's wording meets the identifiers it is about.
    assert set(tokenize("recording findings")) & set(tokenize("record_finding")) >= {"record"}
    assert set(tokenize("enabled")) == set(tokenize("enable"))
    assert set(tokenize("ranks")) == set(tokenize("rank"))
    assert "record_finding" in tokenize("record_finding")  # exact identifiers survive


def test_token_benchmark_harness_runs_on_the_seeded_fixture() -> None:
    from tests.benchmarks.tokens import SEEDED_TASKS, benchmark_repo

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "repos" / "seeded"
    report = benchmark_repo(fixture, SEEDED_TASKS[:2])
    assert report["tasks_run"] == 2
    assert report["search_top3"] == 2
    assert all(t["with_prism"] > 0 and t["without"] > 0 for t in report["tasks"])


def test_store_requires_an_index(tiny_repo: Path) -> None:
    with pytest.raises(IndexMissingError):
        IndexStore.open(tiny_repo)
    apply_init(plan_init(tiny_repo))
    with pytest.raises(IndexMissingError, match="prism scan"):
        IndexStore.open(tiny_repo)


def test_locate_tiers(store: IndexStore) -> None:
    exact = api.op_locate(store, "shop.money.Money")["candidates"]
    assert exact[0]["id"] == "shop.money.Money" and exact[0]["match"] == "exact"
    suffix = api.op_locate(store, "apply_discount")["candidates"]
    assert [c["id"] for c in suffix] == ["shop.pricing.discounts.apply_discount"]
    assert suffix[0]["lines"] == [8, 14]
    files = api.op_locate(store, "checkout/cart.py")["candidates"]
    assert files[0]["kind"] == "file"
    fuzzy = api.op_locate(store, "aply_discount")["candidates"]
    assert fuzzy[0]["match"] == "fuzzy"
    with pytest.raises(NotFoundError):
        api.op_locate(store, "zzzzqqq")


def test_resolution_forms(store: IndexStore) -> None:
    by_line = api.op_context(store, "src/shop/checkout/cart.py:30")
    assert by_line["target"]["id"] == "shop.checkout.cart.Cart.total"
    by_file = api.op_context(store, "src/shop/pricing/rules.py")
    assert by_file["target"]["kind"] == "file"
    assert {s["id"] for s in by_file["symbols"]} >= {
        "shop.pricing.rules.Rule",
        "shop.pricing.rules.eligible_rules",
    }
    by_module = api.op_context(store, "shop.pricing")
    assert by_module["submodules"] == ["shop.pricing.discounts", "shop.pricing.rules"]


def test_ambiguity_is_reported_not_guessed(store: IndexStore) -> None:
    with pytest.raises(AmbiguousTargetError) as info:
        api.op_context(store, "__init__")
    ids = [c["id"] for c in info.value.details["candidates"]]
    assert "shop.checkout.cart.Cart.__init__" in ids and "shop.pricing.rules.Rule.__init__" in ids


def test_not_found_suggests(store: IndexStore) -> None:
    with pytest.raises(NotFoundError) as info:
        api.op_context(store, "apply_dicount")
    assert "shop.pricing.discounts.apply_discount" in info.value.details["suggestions"]
    assert info.value.to_dict()["error"] == "not_found"


def test_context_pack_contents(store: IndexStore) -> None:
    pack = api.op_context(store, "apply_discount")
    assert pack["target"]["file"] == "src/shop/pricing/discounts.py"
    assert pack["summary"] == "Apply the best eligible discount to an amount."
    assert [c["id"] for c in pack["callers"]][:1] == ["shop.checkout.cart.Cart.total"]
    assert {c["id"] for c in pack["callees"]} == {
        "shop.pricing.rules.eligible_rules",
        "shop.money.Money.scale",
    }
    assert pack["tests"] == ["tests/test_discounts.py"]
    assert pack["read_list"][0]["why"] == "target"
    whys = {item["why"] for item in pack["read_list"]}
    assert {"caller", "callee", "test"} <= whys
    assert pack["blast_radius"]["files"] >= 3
    assert pack["budget"]["used"] <= pack["budget"]["requested"]


def test_context_budget_is_enforced(store: IndexStore) -> None:
    small = api.op_context(store, "shop.money.Money", budget=100)
    assert small["budget"]["used"] <= 100 or len(small["read_list"]) == 1
    default = api.op_context(store, "shop.money.Money")
    assert estimate_tokens(render.render_context(default)) <= 2000
    assert default["budget"]["used"] <= 2000
    assert len(default["read_list"]) >= len(small["read_list"])


def test_with_source_and_depth(store: IndexStore) -> None:
    pack = api.op_context(store, "apply_discount", with_source=True, depth=2)
    assert "def apply_discount" in pack["source"]
    assert any(item["why"] == "caller (2 hops)" for item in pack["read_list"])


def test_class_pack_lists_members(store: IndexStore) -> None:
    pack = api.op_context(store, "shop.checkout.cart.Cart")
    assert "total(self, coupon: float | None = None) -> Money" in pack["members"]


def test_impact(store: IndexStore) -> None:
    data = api.op_impact(store, "shop.money.Money")
    first = data["dependents"][0]
    assert first["distance"] == 1
    assert "shop.pricing.discounts.apply_discount" in first["symbols"]
    assert data["tests"] == [
        "tests/test_cart.py",
        "tests/test_discounts.py",
        "tests/test_orders.py",
    ]
    file_level = api.op_impact(store, "src/shop/config.py")
    files = {f for level in file_level["dependents"] for f in level["files"]}
    assert "src/shop/db/session.py" in files


def test_search_ranks_relevant_symbols_first(store: IndexStore) -> None:
    hits = api.op_search(store, "discount coupon")["hits"]
    assert hits[0]["id"] == "shop.pricing.discounts.apply_discount"
    assert (
        api.op_search(store, "payment capture")["hits"][0]["id"] == "shop.checkout.payment.capture"
    )
    assert api.op_search(store, "   ")["hits"] == []


def test_module_summaries(store: IndexStore) -> None:
    data = api.op_module(store, "pricing")
    assert data["module"] == "shop.pricing"
    assert "apply_discount" in data["text"] and "<!-- prism:narrative:summary -->" in data["text"]
    assert api.op_module(store, "shop.pricing.rules")["module"] == "shop.pricing"
    with pytest.raises(NotFoundError):
        api.op_module(store, "nonexistent")


def test_brief_budget_and_freshness(store: IndexStore) -> None:
    data = api.op_brief(store.root)
    assert data["freshness"] == "PRISM · index fresh"
    assert estimate_tokens(render.render_brief(data)) <= BRIEF_TOKEN_LIMIT
    (store.root / "src" / "shop" / "new.py").write_text("x = 1\n")
    assert "1 files changed" in api.op_brief(store.root)["freshness"]


def test_activity_trail_records_ids_only(store: IndexStore) -> None:
    api.op_context(store, "apply_discount")
    api.op_search(store, "cart")
    events = read_activity(store.root)
    assert [e["op"] for e in events][-2:] == ["context", "search"]
    assert events[-2]["ids"] == ["shop.pricing.discounts.apply_discount"]


def test_cache_rebuilds_after_scan(store: IndexStore) -> None:
    assert store.is_current()
    (store.root / "src" / "shop" / "extra.py").write_text("def extra_thing():\n    pass\n")
    scan(store.root)
    assert not store.is_current()
    fresh = IndexStore.open(store.root)
    assert fresh.symbol("shop.extra.extra_thing") is not None
    fresh.close()
