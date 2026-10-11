"""Classify disposable-cache failures consistently across CLI, MCP, and hooks."""

from __future__ import annotations

import sqlite3

from prism.core.errors import PrismError


class IndexQueryError(PrismError):
    code = "index_error"


class IndexBusyError(PrismError):
    code = "index_busy"


def database_problem(exc: sqlite3.DatabaseError) -> PrismError | None:
    code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return None  # only these errors justify destructive disposable-cache recovery
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return IndexBusyError(
            "Index is busy updating; retry at most once, then use bounded local search.",
            retryable=True,
        )
    return IndexQueryError(
        "PRISM retrieval failed; use bounded local search, without repeating the lookup or rebuilding.",
        cause=type(exc).__name__,
        retryable=False,
    )
