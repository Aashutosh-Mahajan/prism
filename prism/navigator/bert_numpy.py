"""A sentence-embedding model run with NumPy alone, for fast local semantic retrieval.

`sentence-transformers` imports PyTorch and the whole `transformers` package: tens of seconds
on some machines, far longer than a prompt hook or a CLI query may take. A small BERT encoder
with mean pooling (the `all-MiniLM-L6-v2` family) is only a few matrix products, so this module
runs exactly that forward pass from the model's own `model.safetensors` and `tokenizer.json`,
needing only `numpy`, `tokenizers` and `safetensors` (all already required by
sentence-transformers, so the `[semantic]` extra adds nothing). It loads in well under a second.

Nothing is downloaded: the model is a local directory or an entry already in the Hugging Face
cache. Models that are not BERT with mean pooling are rejected; the caller then falls back to
sentence-transformers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MAX_TOKENS = 256
BATCH = 32


class UnsupportedModel(Exception):
    """The model is missing locally or is not a mean-pooled BERT encoder."""


def _hub_cache() -> Path:
    explicit = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if explicit:
        return Path(explicit)
    home = os.environ.get("HF_HOME")
    return Path(home) / "hub" if home else Path.home() / ".cache" / "huggingface" / "hub"


def model_dir(model: str) -> Path:
    """The local directory holding `model`: a path, or a snapshot in the Hugging Face cache."""
    path = Path(model).expanduser()
    if path.is_dir():
        return path
    repo = _hub_cache() / ("models--" + model.replace("/", "--"))
    snapshots = repo / "snapshots"
    try:
        ref = (repo / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        ref = ""
    candidates = [snapshots / ref] if ref else []
    if snapshots.is_dir():
        candidates += sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if (candidate / "model.safetensors").is_file() and (candidate / "tokenizer.json").is_file():
            return candidate
    raise UnsupportedModel(f"model '{model}' is not available locally")


def _erf(x: Any) -> Any:
    """Abramowitz & Stegun 7.1.26 (max error 1.5e-7): exact-GELU without SciPy."""
    import numpy as np

    sign = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    poly = t * (
        0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))
    )
    return sign * (1.0 - poly * np.exp(-a * a))


class NumpyBertEmbedder:
    """Mean-pooled, L2-normalised sentence embeddings from a BERT encoder."""

    def __init__(self, model: str) -> None:
        try:
            import numpy as np
            from safetensors.numpy import load_file
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise UnsupportedModel("numpy, tokenizers and safetensors are required") from exc
        directory = model_dir(model)
        try:
            config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UnsupportedModel("model config.json is missing or invalid") from exc
        if config.get("model_type") != "bert" or config.get("hidden_act", "gelu") != "gelu":
            raise UnsupportedModel("only BERT encoders with GELU are supported")
        pooling = directory / "1_Pooling" / "config.json"
        if pooling.is_file():
            mode = json.loads(pooling.read_text(encoding="utf-8"))
            if not mode.get("pooling_mode_mean_tokens") or any(
                mode.get(k)
                for k in (
                    "pooling_mode_cls_token",
                    "pooling_mode_max_tokens",
                    "pooling_mode_mean_sqrt_len_tokens",
                )
            ):
                raise UnsupportedModel("only mean pooling is supported")
        max_tokens = MAX_TOKENS
        st_config = directory / "sentence_bert_config.json"
        if st_config.is_file():
            max_tokens = int(
                json.loads(st_config.read_text(encoding="utf-8")).get("max_seq_length", max_tokens)
            )
        self._np = np
        weights = load_file(str(directory / "model.safetensors"))
        self._w = {k.removeprefix("bert."): v.astype(np.float32) for k, v in weights.items()}
        if "embeddings.word_embeddings.weight" not in self._w:
            raise UnsupportedModel("unexpected weight layout")
        # Dense weights transposed once into contiguous memory: a product with a transposed
        # view misses the BLAS fast path and is two orders of magnitude slower.
        for key in [
            k
            for k in self._w
            if k.startswith("encoder.") and k.endswith(".weight") and "LayerNorm" not in k
        ]:
            self._w[key] = np.ascontiguousarray(self._w[key].T)
        self._layers = int(config["num_hidden_layers"])
        self._heads = int(config["num_attention_heads"])
        self._eps = float(config.get("layer_norm_eps", 1e-12))
        limit = min(max_tokens, int(config.get("max_position_embeddings", 512)))
        self._tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=limit)
        self._tokenizer.no_padding()
        self.name = model

    def _norm(self, x: Any, prefix: str) -> Any:
        np = self._np
        mean = x.mean(-1, keepdims=True)
        var = ((x - mean) ** 2).mean(-1, keepdims=True)
        return (x - mean) / np.sqrt(var + self._eps) * self._w[prefix + ".weight"] + self._w[
            prefix + ".bias"
        ]

    def _dense(self, x: Any, prefix: str) -> Any:
        weight = self._w[prefix + ".weight"]  # already (in, out)
        flat = x.reshape(-1, x.shape[-1]) @ weight + self._w[prefix + ".bias"]
        return flat.reshape(*x.shape[:-1], weight.shape[1])

    def _encode_batch(self, ids: Any, mask: Any) -> Any:
        np = self._np
        w = self._w
        batch, length = ids.shape
        x = (
            w["embeddings.word_embeddings.weight"][ids]
            + w["embeddings.position_embeddings.weight"][:length][None, :, :]
            + w["embeddings.token_type_embeddings.weight"][0]
        )
        x = self._norm(x, "embeddings.LayerNorm")
        hidden = x.shape[-1]
        head = hidden // self._heads
        bias = ((1.0 - mask[:, None, None, :]) * -1e9).astype(np.float32)
        # NumPy scalars are "strong" types: a float64 one would silently upcast every activation.
        scale = np.float32(1.0 / np.sqrt(head))
        inv_root2 = np.float32(1.0 / np.sqrt(2.0))
        for i in range(self._layers):
            p = f"encoder.layer.{i}."

            def split(t: Any) -> Any:
                parts = t.reshape(batch, length, self._heads, head).transpose(0, 2, 1, 3)
                return np.ascontiguousarray(parts)

            q = split(self._dense(x, p + "attention.self.query"))
            k = split(self._dense(x, p + "attention.self.key"))
            v = split(self._dense(x, p + "attention.self.value"))
            scores = q @ np.ascontiguousarray(k.transpose(0, 1, 3, 2)) * scale + bias
            scores -= scores.max(-1, keepdims=True)
            probs = np.exp(scores)
            probs /= probs.sum(-1, keepdims=True)
            context = (probs @ v).transpose(0, 2, 1, 3).reshape(batch, length, hidden)
            x = self._norm(x + self._dense(context, p + "attention.output.dense"),
                           p + "attention.output.LayerNorm")  # fmt: skip
            inner = self._dense(x, p + "intermediate.dense")
            inner = 0.5 * inner * (1.0 + _erf(inner * inv_root2))
            x = self._norm(x + self._dense(inner, p + "output.dense"), p + "output.LayerNorm")
        weights = mask[:, :, None]
        pooled = (x * weights).sum(1) / np.maximum(weights.sum(1), 1e-9)
        return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)

    def embed_array(self, texts: list[str]) -> Any:
        """Embeddings as a float32 matrix, one normalised row per text."""
        np = self._np
        if not texts:
            return np.zeros((0, self._w["embeddings.word_embeddings.weight"].shape[1]), np.float32)
        encoded = [e.ids for e in self._tokenizer.encode_batch(texts)]
        out = np.zeros((len(texts), self._w["embeddings.word_embeddings.weight"].shape[1]),
                       np.float32)  # fmt: skip
        # Similar lengths together, so padding wastes little work.
        order = sorted(range(len(texts)), key=lambda i: len(encoded[i]))
        for start in range(0, len(order), BATCH):
            chunk = order[start : start + BATCH]
            length = max(len(encoded[i]) for i in chunk)
            ids = np.zeros((len(chunk), length), np.int64)
            mask = np.zeros((len(chunk), length), np.float32)
            for row, i in enumerate(chunk):
                ids[row, : len(encoded[i])] = encoded[i]
                mask[row, : len(encoded[i])] = 1.0
            out[chunk] = self._encode_batch(ids, mask)
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in row] for row in self.embed_array(texts)]
