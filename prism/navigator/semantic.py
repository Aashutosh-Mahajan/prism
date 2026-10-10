"""Optional local semantic retrieval (`pip install prism-ctx[semantic]`).

Each symbol is embedded from its kind, name words, signature, docstring and the first lines of
its body, with a local model. Lexical retrieval finds what a request names; embeddings find
code a request *describes* in other words ("where do expired sessions get cleaned up").

* The model must already be on disk: PRISM never downloads anything. A mean-pooled BERT model
  (the default `all-MiniLM-L6-v2`) runs on NumPy alone (`bert_numpy`), loading in a fraction
  of a second; other models fall back to sentence-transformers.
* Vectors are cached by the hash of the text embedded, in `.aicontext/cache/vectors-*.npz`
  (gitignored), so an update re-embeds only the symbols whose text changed.
* A query never embeds the whole repository: if more than a few symbols lack vectors the
  semantic channel is skipped and the background update fills them in.

Opt in with `semantic = true` in `[tool.prism]` (or `PRISM_SEMANTIC=1`); `prism search
--semantic` uses it on request regardless.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Protocol

from prism.core.errors import UserError
from prism.navigator.cache_db import cache_dir
from prism.navigator.store import IndexStore, SearchHit, SymbolRow

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BM25_WEIGHT = 0.45
BODY_LINES = 8
TEXT_CHARS = 600  # what is embedded per symbol; the model only sees ~256 tokens anyway
QUERY_MAX_NEW = 24  # symbols a query may embed inline before giving up on the channel
EMBEDDED_KINDS = frozenset({"function", "method", "class"})

_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


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
                "this embedding model needs the optional extra: pip install prism-ctx[semantic-full]"
                " (BERT models such as the default only need prism-ctx[semantic])"
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


_EMBEDDERS: dict[str, Embedder] = {}
_LOCK = threading.Lock()


def get_embedder(model: str) -> Embedder:
    """The embedder for `model`, created once per process (the MCP server keeps it loaded)."""
    with _LOCK:
        if model not in _EMBEDDERS:
            from prism.navigator.bert_numpy import NumpyBertEmbedder, UnsupportedModel

            try:
                _EMBEDDERS[model] = NumpyBertEmbedder(model)
            except UnsupportedModel:
                _EMBEDDERS[model] = SentenceTransformerEmbedder(model)
        return _EMBEDDERS[model]


def semantic_model(root: Path) -> str:
    from prism.config import load_config

    value: Any = load_config(root).extra.get("semantic_model", DEFAULT_MODEL)
    return str(value)


def semantic_enabled(root: Path) -> bool:
    """Does the user want embeddings in `prism task` (and hooks) for this repo?"""
    env = os.environ.get("PRISM_SEMANTIC")
    if env is not None:
        return env == "1"
    try:
        from prism.config import load_config

        return load_config(root).extra.get("semantic", False) is True
    except Exception:
        return False


# --- the text embedded per symbol ------------------------------------------------------


def _words(identifier: str) -> str:
    return " ".join(w.lower() for w in _SPLIT.findall(identifier))


def symbol_text(symbol: SymbolRow, lines: list[str] | None) -> str:
    """What a symbol means, in words a request might use: name words, signature, doc, code."""
    owner = symbol.parent.rsplit(".", 1)[-1] if symbol.parent else ""
    head = f"{symbol.kind} {_words(symbol.name)}" + (f" of {_words(owner)}" if owner else "")
    parts = [head, symbol.signature, symbol.doc]
    if lines:
        body = lines[symbol.start : min(symbol.end, symbol.start + BODY_LINES)]
        parts.append("\n".join(line.strip() for line in body if line.strip()))
    return "\n".join(p for p in parts if p)[:TEXT_CHARS]


def _texts(store: IndexStore) -> list[tuple[str, str]]:
    """(symbol id, text) for every embeddable symbol, reading each source file once."""
    from prism.navigator.source_index import SourceReader

    reader = SourceReader(store)
    out: list[tuple[str, str]] = []
    for sym in sorted(store.all_symbols(), key=lambda s: (s.file, s.start, s.id)):
        if sym.kind not in EMBEDDED_KINDS:
            continue
        out.append((sym.id, symbol_text(sym, reader.lines(sym.file))))
    return out


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


# --- the vector cache ------------------------------------------------------------------


def _cache_path(root: Path, embedder: Embedder) -> Path:
    key = hashlib.sha256(embedder.name.encode("utf-8")).hexdigest()[:12]
    return cache_dir(root) / f"vectors-{key}.npz"


def _embed(embedder: Embedder, texts: list[str]) -> Any:
    import numpy as np

    array = getattr(embedder, "embed_array", None)
    matrix = array(texts) if array else np.asarray(embedder.embed(texts), dtype=np.float32)
    matrix = matrix.astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class _Cache:
    """The vector cache file: rows by text hash, plus the ordered symbols of the index it was
    last brought up to date for, so an unchanged index is answered without reading source."""

    def __init__(self, rows: dict[str, Any], fingerprint: str, ids: list[str], digests: list[str]):
        self.rows = rows
        self.fingerprint = fingerprint
        self.ids = ids
        self.digests = digests


_LOADED: dict[Path, tuple[float, _Cache]] = {}


def _load(path: Path) -> _Cache:
    import numpy as np

    empty = _Cache({}, "", [], [])
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return empty
    hit = _LOADED.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with np.load(path, allow_pickle=False) as data:
            matrix = data["matrix"]
            cache = _Cache(
                {str(h): matrix[i] for i, h in enumerate(data["hashes"])},
                str(data["fingerprint"]),
                [str(i) for i in data["ids"]],
                [str(d) for d in data["digests"]],
            )
    except (OSError, ValueError, KeyError):
        return empty
    _LOADED[path] = (mtime, cache)
    return cache


def _save(path: Path, cache: _Cache) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    hashes = sorted(cache.rows)
    matrix: Any = (
        np.asarray(np.stack([cache.rows[h] for h in hashes]), dtype=np.float32)
        if hashes
        else np.zeros((0, 0), np.float32)
    )
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp.npz")
    np.savez(
        tmp,
        hashes=np.asarray(hashes, dtype="U24"),
        matrix=matrix,
        fingerprint=np.asarray(cache.fingerprint),
        ids=np.asarray(cache.ids, dtype=str),
        digests=np.asarray(cache.digests, dtype="U24"),
    )
    os.replace(tmp, path)
    _LOADED.pop(path, None)


def vectors(
    store: IndexStore, embedder: Embedder, max_new: int | None = None
) -> tuple[list[str], Any] | None:
    """(symbol ids, normalised matrix) for the current index, embedding only symbols whose text
    is new. None when more than `max_new` symbols would have to be embedded now."""
    import numpy as np

    from prism.navigator.cache_db import fingerprint

    path = _cache_path(store.root, embedder)
    current = fingerprint(store.manifest)
    cache = _load(path)
    if cache.fingerprint == current and all(d in cache.rows for d in cache.digests):
        ids, digests = cache.ids, cache.digests
    else:
        items = _texts(store)
        ids = [sid for sid, _ in items]
        digests = [_digest(text) for _, text in items]
        missing = sorted({d for d in digests if d not in cache.rows})
        if max_new is not None and len(missing) > max_new:
            return None
        rows = dict(cache.rows)
        if missing:
            text_of = {d: text for d, (_, text) in zip(digests, items, strict=True)}
            new = _embed(embedder, [text_of[d] for d in missing])
            for d, vector in zip(missing, new, strict=True):
                rows[d] = vector
        live = set(digests)
        _save(path, _Cache({d: v for d, v in rows.items() if d in live}, current, ids, digests))
        cache = _load(path)
    if not ids:
        return [], np.zeros((0, 0), np.float32)
    return ids, np.stack([cache.rows[d] for d in digests])


def warm_vectors(root: Path) -> int:
    """Bring the vector cache up to date (background update, `scan`). Returns symbols embedded."""
    if not semantic_enabled(root):
        return 0
    store = IndexStore.open(root)
    try:
        embedder = get_embedder(semantic_model(root))
        before = set(_load(_cache_path(root, embedder)).rows)
        vectors(store, embedder)
        return len(set(_load(_cache_path(root, embedder)).rows) - before)
    finally:
        store.close()


# --- queries ---------------------------------------------------------------------------


def ranking(
    store: IndexStore,
    query: str,
    limit: int = 30,
    embedder: Embedder | None = None,
    max_new: int | None = QUERY_MAX_NEW,
) -> list[tuple[str, float]]:
    """Symbols most similar to `query` as (id, cosine), best first. Empty when the channel is
    unavailable (not enabled, no model, cache cold): retrieval then works lexically as before."""
    import numpy as np

    if embedder is None:
        if not semantic_enabled(store.root):
            return []
        try:
            embedder = get_embedder(semantic_model(store.root))
        except Exception:
            return []
    found = vectors(store, embedder, max_new)
    if found is None or not found[0]:
        return []
    ids, matrix = found
    q = _embed(embedder, [query])[0]
    scores = matrix @ q
    top = np.argsort(-scores, kind="stable")[:limit]
    return [(ids[i], float(scores[i])) for i in top]


def hybrid_search(store: IndexStore, query: str, limit: int, embedder: Embedder) -> list[SearchHit]:
    cosine = dict(
        ranking(store, query, limit=max(limit * 10, 100), embedder=embedder, max_new=None)
    )
    if not cosine:
        return store.search(query, limit)
    lexical = {
        h.ref: h.score for h in store.search(query, max(limit * 5, 50)) if h.kind == "symbol"
    }
    top_lex = max(lexical.values(), default=0.0) or 1.0
    scored: dict[str, float] = {}
    for sid in set(cosine) | set(lexical):
        scored[sid] = (1 - BM25_WEIGHT) * max(0.0, cosine.get(sid, 0.0)) + BM25_WEIGHT * (
            lexical.get(sid, 0.0) / top_lex
        )
    best = sorted(scored, key=lambda s: (-scored[s], s))[:limit]
    return [SearchHit("symbol", sid, round(scored[sid], 4)) for sid in best]
