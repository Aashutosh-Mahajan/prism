"""Optional local semantic search (`pip install prism-ctx[semantic]`).

Embeds each symbol's name, signature, and docstring with a local
sentence-transformers model and blends cosine similarity with BM25. The
model must already be on disk: PRISM loads it with `local_files_only=True`
and `HF_HUB_OFFLINE=1`, so it never downloads anything or touches the
network. Vectors are cached per index fingerprint in `.aicontext/cache/`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Protocol

from prism.core.errors import UserError
from prism.navigator.cache_db import cache_dir, fingerprint
from prism.navigator.store import IndexStore, SearchHit

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BM25_WEIGHT = 0.45


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    def __init__(self, model: str) -> None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise UserError(
                "semantic search needs the optional extra: pip install prism-ctx[semantic]"
            ) from exc
        try:
            self._model = SentenceTransformer(model, local_files_only=True)
        except Exception as exc:
            raise UserError(
                f"embedding model '{model}' is not available locally. PRISM never downloads it; "
                f"fetch it yourself once (e.g. `huggingface-cli download {model}`) or set "
                "`semantic_model` in [tool.prism] to a local path."
            ) from exc
        self.name = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vectors]


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _vectors(store: IndexStore, embedder: Embedder) -> tuple[list[str], list[list[float]]]:
    key = hashlib.sha256(f"{fingerprint(store.manifest)}|{embedder.name}".encode()).hexdigest()[:16]
    path = cache_dir(store.root) / f"embeddings-{key}.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["ids"], data["vectors"]
    symbols = store.all_symbols()
    ids = [s.id for s in symbols]
    texts = [f"{s.name}: {s.signature}. {s.doc}" for s in symbols]
    vectors = [_normalize(v) for v in embedder.embed(texts)] if texts else []
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob("embeddings-*.json"):
        old.unlink(missing_ok=True)
    path.write_text(json.dumps({"ids": ids, "vectors": vectors}), encoding="utf-8")
    return ids, vectors


def hybrid_search(store: IndexStore, query: str, limit: int, embedder: Embedder) -> list[SearchHit]:
    ids, vectors = _vectors(store, embedder)
    if not ids:
        return store.search(query, limit)
    q = _normalize(embedder.embed([query])[0])
    cosine = {
        i: sum(a * b for a, b in zip(q, v, strict=False)) for i, v in zip(ids, vectors, strict=True)
    }
    lexical = {
        h.ref: h.score for h in store.search(query, max(limit * 5, 50)) if h.kind == "symbol"
    }
    top_lex = max(lexical.values(), default=0.0) or 1.0
    scored: dict[str, float] = {}
    for sid, cos in cosine.items():
        scored[sid] = (1 - BM25_WEIGHT) * max(0.0, cos) + BM25_WEIGHT * lexical.get(
            sid, 0.0
        ) / top_lex
    best = sorted(scored, key=lambda s: (-scored[s], s))[:limit]
    return [SearchHit("symbol", sid, round(scored[sid], 4)) for sid in best]


_EMBEDDERS: dict[str, Embedder] = {}


def get_embedder(model: str) -> Embedder:
    if model not in _EMBEDDERS:
        _EMBEDDERS[model] = SentenceTransformerEmbedder(model)
    return _EMBEDDERS[model]


def semantic_model(root: Path) -> str:
    from prism.config import load_config

    value: Any = load_config(root).extra.get("semantic_model", DEFAULT_MODEL)
    return str(value)
