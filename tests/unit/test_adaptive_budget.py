from types import SimpleNamespace

import pytest

from prism.navigator import api


@pytest.mark.parametrize("count,initial", [(100, 800), (500, 1200)])
def test_only_delivered_attempt_updates_memory(
    monkeypatch: pytest.MonkeyPatch, count: int, initial: int
) -> None:
    store = SimpleNamespace(
        conn=SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: [count]))
    )
    budgets = []

    def retrieve(
        store: object, query: str, budget: int, seen: set, *args: object, **kwargs: object
    ) -> dict:
        budgets.append(budget)
        seen.add(("source.py", budget, budget))
        return {"confidence": "high", "sufficient": budget == 2000}

    monkeypatch.setattr(api, "op_task", retrieve)
    seen: set[tuple[str, int, int]] = set()
    pack = api.adaptive_task(store, "change the source", seen=seen)  # type: ignore[arg-type]
    assert pack["sufficient"]
    assert budgets == [initial, 2000]
    assert seen == {("source.py", 2000, 2000)}


def test_weak_matches_do_not_expand(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SimpleNamespace(
        conn=SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: [100]))
    )
    budgets = []

    def retrieve(store: object, query: str, budget: int, *args: object, **kwargs: object) -> dict:
        budgets.append(budget)
        return {"confidence": "low", "sufficient": False}

    monkeypatch.setattr(api, "op_task", retrieve)
    api.adaptive_task(store, "unknown concept")  # type: ignore[arg-type]
    assert budgets == [800]


@pytest.mark.parametrize("mode", ["auto", "overview"])
def test_overview_does_not_build_an_expansion_it_cannot_deliver(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    store = SimpleNamespace(
        conn=SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: [100]))
    )
    budgets = []

    def retrieve(store: object, query: str, budget: int, *args: object, **kwargs: object) -> dict:
        budgets.append(budget)
        return {"intent": "overview", "confidence": "medium", "sufficient": False}

    monkeypatch.setattr(api, "op_task", retrieve)
    pack = api.adaptive_task(store, "architecture", mode=mode)  # type: ignore[arg-type]
    assert not pack["sufficient"]
    assert budgets == [800]
