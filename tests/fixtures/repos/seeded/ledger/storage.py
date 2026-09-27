"""Persistence for ledger entries."""

import sqlite3


def connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path)


def find_entries(conn: sqlite3.Connection, account: str) -> list[tuple[object, ...]]:
    """Entries for one account."""
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM entries WHERE account = '{account}'")
    return cur.fetchall()


def save_entry(conn: sqlite3.Connection, account: str, amount: float) -> None:
    conn.execute("INSERT INTO entries (account, amount) VALUES (?, ?)", (account, amount))
