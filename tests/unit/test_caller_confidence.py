from types import SimpleNamespace

import pytest

from prism.navigator import task_pack


def test_inferred_caller_cap_is_shared_across_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    primaries = [SimpleNamespace(id=f"module.target{i}", file="module.py") for i in range(2)]

    def callers(identity: str) -> list:
        return [
            SimpleNamespace(
                symbol=SimpleNamespace(id=f"{identity}.caller{i}", file=f"caller{i}.py"),
                line=1,
                confidence="high" if i == 3 else "medium",
                resolution="resolved" if i == 3 else "name",
            )
            for i in range(4)
        ]

    store = SimpleNamespace(callers=callers, callees=lambda _: [], _is_test=lambda _: False)
    monkeypatch.setattr(task_pack, "_related_tests", lambda *args: [])
    monkeypatch.setattr(
        task_pack, "dependents", lambda *args, **kwargs: {"symbols": [], "files": {}}
    )
    pack = {
        "intent": "edit",
        "confidence": "high",
        "stale_sources": 0,
        "blocks": [],
        "next": "",
        "budget": {"requested": 2000, "used_est": 0},
    }
    task_pack._links(
        store, None, SimpleNamespace(lines=lambda _: ["target()"]), pack, primaries, 2000, False
    )  # type: ignore[arg-type]
    links = [item for item in pack["links"] if item["role"] == "caller"]
    assert sum(item["uncertain"] for item in links) == 3
    assert {item["target"] for item in links if not item["uncertain"]} == {
        item.id for item in primaries
    }
    for target in primaries:
        assert next(item for item in links if item["target"] == target.id)["confidence"] == "high"
    assert task_pack.render_task(pack).count("~ inferred caller") == 1
