"""Phase 5: communities, decisions, semantic search, watch, doctor, migrate."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from prism.core.errors import NotFoundError, UserError
from prism.graph.communities import louvain
from prism.lifecycle import apply_init, plan_init, scan, set_paused
from prism.maintenance import doctor, migrate, watch
from prism.navigator import api
from prism.navigator.store import IndexStore
from prism.writers.decisions import add_decision, get_decision, list_decisions

FIXTURES = Path(__file__).parents[1] / "fixtures" / "repos"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = shutil.copytree(FIXTURES / "small", tmp_path / "small")
    apply_init(plan_init(root))
    scan(root)
    return root


def test_louvain_finds_obvious_communities() -> None:
    a = [("a1", "a2", 1.0), ("a2", "a3", 1.0), ("a1", "a3", 1.0)]
    b = [("b1", "b2", 1.0), ("b2", "b3", 1.0), ("b1", "b3", 1.0)]
    result = louvain(["a1", "a2", "a3", "b1", "b2", "b3", "lonely"], [*a, *b, ("a3", "b1", 0.1)])
    assert result["a1"] == result["a2"] == result["a3"]
    assert result["b1"] == result["b2"] == result["b3"]
    assert result["a1"] != result["b1"] and result["lonely"] not in (result["a1"], result["b1"])
    assert result == louvain(
        ["lonely", "b3", "b2", "b1", "a3", "a2", "a1"], [*reversed(a), *b, ("a3", "b1", 0.1)]
    )


def test_communities_in_index(repo: Path) -> None:
    modules = {
        m["id"]: m
        for m in json.loads((repo / ".aicontext" / "dependency_graph.json").read_text())["modules"]
    }
    assert (
        modules["shop.pricing.discounts"]["community"] == modules["shop.pricing.rules"]["community"]
    )
    assert modules["tests.test_cart"]["community"] == -1


def test_decisions(repo: Path) -> None:
    first = add_decision(
        repo,
        "Store money as integer cents",
        "Floats caused rounding bugs.",
        "Use Money(cents: int) everywhere.",
        symbols=["shop.money.Money"],
    )
    assert first["id"] == "0001" and first["file"].startswith(
        ".aicontext/decisions/0001-store-money"
    )
    second = add_decision(
        repo,
        "Round half-even at the edges",
        "Half-up drifted totals.",
        "Round half-even when converting.",
        supersedes="1",
    )
    assert second["id"] == "0002"
    assert get_decision(repo, "0001")["status"] == "superseded"
    assert [d["title"] for d in list_decisions(repo)] == [
        "Store money as integer cents",
        "Round half-even at the edges",
    ]
    store = IndexStore.open(repo)
    hits = api.op_search(store, "rounding floats")["hits"]
    assert hits[0]["kind"] == "decision"
    store.close()
    with pytest.raises(UserError):
        add_decision(repo, "x", "c", "d")
    with pytest.raises(UserError):
        add_decision(repo, "A valid title", "", "d")
    with pytest.raises(NotFoundError):
        get_decision(repo, "9")
    assert all(c.name != "artifacts" or c.status == "ok" for c in doctor(repo))


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder standing in for a local model."""

    name = "fake"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * 64
            for word in text.lower().replace("_", " ").replace(".", " ").split():
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
            out.append(v)
        return out


def test_semantic_search_blends_embeddings(repo: Path) -> None:
    store = IndexStore.open(repo)
    data = api.op_search(store, "discount", 5, semantic=True, embedder=FakeEmbedder())
    assert data["mode"] == "hybrid"
    assert data["hits"][0]["id"] == "shop.pricing.discounts.apply_discount"
    assert list((repo / ".aicontext" / "cache").glob("embeddings-*.json"))
    again = api.op_search(store, "discount", 5, semantic=True, embedder=FakeEmbedder())
    assert again["hits"] == data["hits"]  # served from the vector cache
    store.close()


def test_semantic_search_without_model_is_a_clear_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prism.navigator import semantic

    def missing(model: str) -> None:
        raise UserError(f"embedding model '{model}' is not available locally")

    monkeypatch.setattr(semantic, "SentenceTransformerEmbedder", missing)
    semantic._EMBEDDERS.clear()
    store = IndexStore.open(repo)
    with pytest.raises(UserError, match="not available locally"):
        api.op_search(store, "discount", semantic=True)
    store.close()


def test_watch_updates_and_respects_pause(repo: Path) -> None:
    updates = []
    ticks = iter(range(3))

    def stop() -> bool:
        tick = next(ticks, None)
        if tick == 1:
            (repo / "src" / "shop" / "watched.py").write_text("def watched():\n    pass\n")
        return tick is None

    watch(repo, interval=0.01, on_update=updates.append, stop=stop)
    assert len(updates) == 1 and updates[0].added == ("src/shop/watched.py",)
    set_paused(repo, True)
    (repo / "src" / "shop" / "ignored.py").write_text("x = 1\n")
    paused_updates: list[object] = []
    ticks = iter(range(2))
    watch(
        repo, interval=0.01, on_update=paused_updates.append, stop=lambda: next(ticks, None) is None
    )
    assert paused_updates == []


def test_doctor_and_migrate(repo: Path, tmp_path: Path) -> None:
    checks = {c.name: c for c in doctor(repo)}
    assert checks["initialized"].status == "ok"
    assert checks["manifest schema"].status == "ok"
    assert checks["consent"].status == "ok"
    (repo / ".aicontext" / "symbols.json").write_text("{}")
    assert {c.name: c for c in doctor(repo)}["artifacts"].status == "warn"
    result = migrate(repo)
    assert result["rebuilt"] and result["from"] == result["to"] == "1.0"
    assert {c.name: c for c in doctor(repo)}["artifacts"].status == "ok"
    fresh = tmp_path / "empty"
    fresh.mkdir()
    assert {c.name: c for c in doctor(fresh)}["initialized"].status == "warn"
