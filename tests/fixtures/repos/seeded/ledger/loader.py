"""Load exported ledgers."""

import pickle

from ledger.pricing import apply_discount


def load_export(blob: bytes) -> object:
    return pickle.loads(blob)


def reprice(prices: list[float]) -> list[float]:
    return [apply_discount(p, 0.1, 0.05) for p in prices]
