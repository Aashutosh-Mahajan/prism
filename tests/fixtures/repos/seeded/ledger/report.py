"""Paged reports."""

from ledger.utils import cents


def page(entries: list[float], page_number: int, size: int = 10) -> list[int]:
    """Return one page (1-based) of entries in cents."""
    start = page_number * size
    return [cents(e) for e in entries[start : start + size]]


def total(entries: list[float]) -> int:
    return sum(cents(e) for e in entries)
