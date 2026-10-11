"""Wrapper-following: the edit site behind a facade, without mistaking a utility for one."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.navigator import api as nav
from prism.navigator.delegation import follow, related
from prism.navigator.store import IndexStore
from tests.benchmarks.retrieval_eval import index_fixture


@pytest.fixture()
def layered(tmp_path: Path) -> IndexStore:
    store = IndexStore.open(index_fixture("layered", tmp_path))
    yield store
    store.close()


def test_facade_resolves_to_the_class_that_holds_the_behaviour(layered: IndexStore) -> None:
    facade = layered.symbol("lib.api.Field.min_length")
    assert facade is not None
    [found] = follow(layered, [facade])
    assert found.target.id == "lib.checks.MinLengthCheck"
    assert found.wrappers == ("lib.api.Field.min_length", "lib.rules.min_length")


def test_a_symbol_with_a_real_body_is_not_a_wrapper(layered: IndexStore) -> None:
    check = layered.symbol("lib.checks.MinLengthCheck")
    assert check is not None
    assert follow(layered, [check]) == []


def test_a_used_utility_is_not_a_delegation(tmp_path: Path) -> None:
    store = IndexStore.open(index_fixture("small", tmp_path))
    try:
        total = store.symbol("shop.checkout.cart.Cart.total")
        assert total is not None
        assert follow(store, [total]) == []  # it builds a Money; it does not delegate to it
    finally:
        store.close()


def test_relatedness_ignores_glue_words(layered: IndexStore) -> None:
    run = layered.symbol("lib.api.Field.validate")
    money = layered.symbol("lib.checks.RoundCheck")
    assert run is not None and money is not None
    assert not related(run, money)


def test_task_packet_contains_the_implementation_not_only_the_facade(layered: IndexStore) -> None:
    pack = nav.op_task(
        layered,
        "Field().min_length(3) lets through emoji values shorter than three characters. "
        "Fix how the length is counted.",
        1200,
        None,
        "auto",
        None,
    )
    shown = [(b["file"], b["role"]) for b in pack["blocks"]]
    assert ("lib/checks.py", "implementation") in shown
    assert shown.index(("lib/checks.py", "implementation")) < shown.index(
        ("lib/api.py", "candidate")
    )
