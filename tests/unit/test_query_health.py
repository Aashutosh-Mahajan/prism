import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app, handle_errors
from prism.lifecycle import apply_init, plan_init, scan
from prism.maintenance import doctor
from prism.navigator import cache_db


def test_doctor_detects_query_failure_in_an_otherwise_valid_index(
    small_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_init(plan_init(small_repo))
    scan(small_repo)

    def fail(*args, **kwargs):
        raise sqlite3.IntegrityError("UNIQUE constraint failed")

    monkeypatch.setattr("prism.navigator.store.IndexStore.open", fail)
    check = next(c for c in doctor(small_repo) if c.name == "query cache")
    assert check.status == "fail" and "IntegrityError" in check.detail


def test_cli_programming_error_is_not_retried_or_purged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        cache_db, "purge_disposable_caches", lambda root: pytest.fail("SQL error purged caches")
    )

    @app.command("_sql-recovery-contract")
    @handle_errors
    def fail() -> None:
        calls.append(True)
        raise sqlite3.IntegrityError("duplicate doc")

    try:
        result = CliRunner().invoke(app, ["_sql-recovery-contract"])
        assert result.exit_code == 3 and len(calls) == 1
        assert "bounded local search" in result.output
    finally:
        app.registered_commands[:] = [
            c for c in app.registered_commands if c.name != "_sql-recovery-contract"
        ]
