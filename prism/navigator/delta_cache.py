"""Publish immutable SQLite generations using row deltas from a previous snapshot.

Independently implemented from the selective-sync pattern used by TokenSave.
The previous generation stays readable; only a completed temp database is published.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Iterable
from typing import Any


class DeltaConnection(sqlite3.Connection):
    rows_inserted: int = 0
    rows_deleted: int = 0

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        # A compatible generation already has the complete schema. No schema
        # migration is attempted on the previous generation or its readers.
        return self.execute("SELECT 1")

    def executemany(self, sql: str, parameters: Iterable[Any], /) -> sqlite3.Cursor:
        match = re.fullmatch(r"INSERT INTO ([a-z_]+) VALUES \([?,]+\)", sql)
        if match is None:
            raise ValueError("delta writer only accepts internal whole-table row batches")
        table = match[1]
        desired = Counter(tuple(row) for row in parameters)
        existing: dict[tuple[Any, ...], list[int]] = {}
        for row in self.execute(f"SELECT rowid, * FROM {table}"):
            existing.setdefault(tuple(row[1:]), []).append(row[0])
        removed = []
        for row, identities in existing.items():
            removed.extend(identities[desired[row] :])
        for offset in range(0, len(removed), 500):
            batch = removed[offset : offset + 500]
            self.execute(
                f"DELETE FROM {table} WHERE rowid IN ({','.join('?' for _ in batch)})", batch
            )
        added = [
            row
            for row, count in desired.items()
            for _ in range(max(0, count - len(existing.get(row, []))))
        ]
        self.rows_deleted += len(removed)
        self.rows_inserted += len(added)
        return super().executemany(sql, added)
