"""Synchronise the ledger with the bank feed."""

from ledger.storage import save_entry


def import_feed(conn: object, rows: list[dict[str, object]]) -> int:
    """Import rows; returns the number imported."""
    imported = 0
    for row in rows:
        try:
            save_entry(conn, str(row["account"]), float(row["amount"]))  # type: ignore[arg-type]
            imported += 1
        except:
            pass
    return imported
