"""The optional embedding channel in `prism task`, and the NumPy sentence encoder."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import ClassVar

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import api, semantic
from prism.navigator.store import IndexStore

PARAPHRASE = "split a list into fixed-size groups"


class ConceptEmbedder:
    """Deterministic stand-in for a model: maps a few synonyms onto shared concept axes, so a
    paraphrase lands near the code it describes although no word matches."""

    name = "concept-fake"
    CONCEPTS: ClassVar[dict[str, str]] = {
        "chunk": "batch", "split": "batch", "groups": "batch", "size": "batch",
        "fixed": "batch", "pieces": "batch",
        "json": "serial", "dumps": "serial",
    }  # fmt: skip

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * 512
            for word in text.lower().replace("_", " ").replace("(", " ").split():
                key = self.CONCEPTS.get(word.strip(".,:-"), word)
                v[int(hashlib.md5(key.encode()).hexdigest(), 16) % 512] += 1.0
            out.append(v)
        return out


@pytest.fixture
def indexed(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> ConceptEmbedder:
    embedder = ConceptEmbedder()
    monkeypatch.setattr(semantic, "get_embedder", lambda model: embedder)
    monkeypatch.setenv("PRISM_SEMANTIC", "1")
    return embedder


def test_semantic_channel_is_off_unless_enabled(
    indexed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRISM_SEMANTIC", raising=False)
    assert not semantic.semantic_enabled(indexed)
    store = IndexStore.open(indexed)
    try:
        assert semantic.ranking(store, PARAPHRASE) == []
    finally:
        store.close()
    (indexed / "pyproject.toml").write_text("[tool.prism]\nsemantic = true\n", encoding="utf-8")
    assert semantic.semantic_enabled(indexed)


def test_paraphrase_finds_code_no_word_matches(indexed: Path, fake_model: ConceptEmbedder) -> None:
    assert semantic.warm_vectors(indexed) > 0  # what the background update does
    request = "split stuff into pieces"  # not one word of chunk()'s name, signature or body
    store = IndexStore.open(indexed)
    try:
        with pytest.MonkeyPatch.context() as off:
            off.setenv("PRISM_SEMANTIC", "0")
            assert api.op_task(store, request, 2000)["blocks"] == []
        pack = api.op_task(store, request, 2000)
        similar = [b for b in pack["blocks"] if b["role"] == "similar"]
        assert similar and similar[0]["symbol"] == "shop.utils.chunk"
        # Found only by similarity: offered as a candidate, never as proof.
        assert pack["confidence"] == "medium" and not pack["sufficient"]
    finally:
        store.close()


def test_exact_requests_are_not_diluted(indexed: Path, fake_model: ConceptEmbedder) -> None:
    store = IndexStore.open(indexed)
    try:
        pack = api.op_task(store, "apply_discount", 2000)
        assert pack["blocks"][0]["symbol"] == "shop.pricing.discounts.apply_discount"
        assert all(b["role"] != "similar" for b in pack["blocks"])
    finally:
        store.close()


def test_vectors_are_incremental_and_queries_never_embed_the_repo(
    indexed: Path, fake_model: ConceptEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    original = fake_model.embed

    def counting(texts: list[str]) -> list[list[float]]:
        calls.append(len(texts))
        return original(texts)

    monkeypatch.setattr(fake_model, "embed", counting)
    store = IndexStore.open(indexed)
    try:
        # A cold cache with more symbols than a query may embed: the channel stays silent.
        assert semantic.ranking(store, PARAPHRASE, max_new=2) == []
        assert calls == []
        ids, matrix = semantic.vectors(store, fake_model) or ([], None)
        assert len(ids) == len(matrix) and calls == [len(ids)]
        calls.clear()
        semantic.ranking(store, PARAPHRASE, max_new=2)
        assert calls == [1]  # only the query
    finally:
        store.close()
    utils = indexed / "src" / "shop" / "utils.py"
    utils.write_text(utils.read_text(encoding="utf-8") + "\n\ndef added() -> int:\n    return 1\n")
    from prism.lifecycle import update

    update(indexed)
    calls.clear()
    store = IndexStore.open(indexed)
    try:
        semantic.ranking(store, PARAPHRASE, max_new=2)
        assert calls == [1, 1]  # the new symbol, then the query
    finally:
        store.close()


def test_numpy_encoder_matches_reference_properties() -> None:
    from prism.navigator.bert_numpy import NumpyBertEmbedder, UnsupportedModel

    try:
        model = NumpyBertEmbedder(semantic.DEFAULT_MODEL)
    except UnsupportedModel:
        pytest.skip("default embedding model is not available locally")
    vectors = model.embed(
        ["split a list into fixed-size groups", "def chunk(items, size): return batches", "x"]
    )
    for v in vectors:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-4)
    cos = [sum(a * b for a, b in zip(vectors[0], v, strict=True)) for v in vectors[1:]]
    assert cos[0] > cos[1]
    again = model.embed(["split a list into fixed-size groups"])[0]
    assert max(abs(a - b) for a, b in zip(again, vectors[0], strict=True)) < 1e-5
