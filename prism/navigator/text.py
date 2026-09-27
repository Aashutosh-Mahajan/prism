"""Tokenization and BM25 scoring for `prism search`."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

_WORD = re.compile(r"[A-Za-z0-9]+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
        "self",
        "cls",
        "none",
        "return",
        "returns",
        "def",
        "class",
        "py",
    ]
)
K1 = 1.2
B = 0.75


# Longest first; each strip must leave a stem of at least three letters.
_SUFFIXES = ("ations", "ation", "ings", "ing", "ies", "ers", "er", "ed", "es", "s", "e")


def stem(word: str) -> str:
    """Light, deterministic suffix stripping so "recording" meets `record` and "enabled"
    meets `enable`. Applied identically to indexed text and queries, so it only has to be
    consistent, not linguistically perfect."""
    if len(word) <= 4 or not word.isalpha():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "lsz":
        word = word[:-1]  # running -> runn -> run
    return word


def tokenize(text: str) -> list[str]:
    """Stemmed words, lowercased, with snake_case and camelCase split. Whole identifiers are
    kept too (unstemmed) so exact names still rank first."""
    out: list[str] = []
    for word in _WORD.findall(text.replace("_", " ")):
        low = word.lower()
        parts = [p.lower() for p in _CAMEL.findall(word)]
        if low not in STOPWORDS:
            out.append(stem(low))
        if len(parts) > 1:
            out.extend(stem(p) for p in parts if p not in STOPWORDS)
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if "_" in ident.strip("_"):
            out.append(ident.lower())
    return out


def term_counts(fields: Iterable[tuple[str, int]]) -> Counter[str]:
    """Weighted bag of words: each (text, weight) field contributes its tokens `weight` times."""
    counts: Counter[str] = Counter()
    for text, weight in fields:
        for tok in tokenize(text):
            counts[tok] += weight
    return counts


def bm25(tf: float, df: int, n_docs: int, doc_len: float, avg_len: float) -> float:
    idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
    norm = tf * (K1 + 1) / (tf + K1 * (1 - B + B * doc_len / max(avg_len, 1e-9)))
    return idf * norm
