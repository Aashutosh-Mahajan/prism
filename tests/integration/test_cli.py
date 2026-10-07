from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from prism import __version__
from prism.cli import app
from prism.consent import registry_path

runner = CliRunner()


def run(*args: str, input: str | None = None):  # type: ignore[no-untyped-def]
    return runner.invoke(app, list(args), input=input)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_version() -> None:
    result = run("--version")
    assert result.exit_code == 0 and __version__ in result.output


def test_global_root_and_session_work_before_the_task_command(tiny_repo: Path) -> None:
    root = str(tiny_repo)
    assert run("init", "--root", root, "--yes").exit_code == 0
    first = run("--root", root, "--session", "global-flags", "task", "apply_discount", "--json")
    assert first.exit_code == 0, first.output
    initial = json.loads(first.output)
    assert any("source" in b for b in initial["blocks"])
    again = run("task", "apply_discount", "--root", root, "--session", "global-flags", "--json")
    assert again.exit_code == 0, again.output
    repeated = json.loads(again.output)
    assert any(b.get("seen") for b in repeated["blocks"]), (initial, repeated)


def test_task_options_override_global_defaults(tiny_repo: Path, tmp_path: Path) -> None:
    root = str(tiny_repo)
    assert run("init", "--root", root, "--yes").exit_code == 0
    result = run(
        "--root",
        str(tmp_path / "missing"),
        "--session",
        "outer",
        "task",
        "apply_discount",
        "--root",
        root,
        "--session",
        "inner",
        "--json",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["blocks"]
    outer = run("--root", root, "--session", "outer", "task", "apply_discount", "--json")
    assert outer.exit_code == 0, outer.output
    assert any("source" in b for b in json.loads(outer.output)["blocks"])


def test_init_shows_plan_and_declining_changes_nothing(tiny_repo: Path) -> None:
    before = snapshot(tiny_repo)
    result = run("init", "--root", str(tiny_repo), input="n\n")
    assert result.exit_code == 0
    assert ".aicontext/manifest.json" in result.output
    assert ".gitignore" in result.output
    assert "Nothing changed." in result.output
    assert snapshot(tiny_repo) == before
    assert not registry_path().exists()


def test_init_yes_scans_and_is_idempotent(tiny_repo: Path) -> None:
    result = run("init", "--root", str(tiny_repo), "--yes")
    assert result.exit_code == 0, result.output
    assert "Indexed 5 files" in result.output
    gitignore = (tiny_repo / ".gitignore").read_text()
    assert ".aicontext/cache/" in gitignore and ".aicontext/audit/scratch/" in gitignore

    before = snapshot(tiny_repo)
    again = run("init", "--root", str(tiny_repo), "--yes", "--no-scan")
    assert again.exit_code == 0
    assert "already initialized" in again.output
    assert snapshot(tiny_repo) == before


def test_init_no_scan(tiny_repo: Path) -> None:
    result = run("init", "--root", str(tiny_repo), "--yes", "--no-scan")
    assert result.exit_code == 0
    assert not (tiny_repo / ".aicontext" / "symbols.json").exists()
    status = json.loads(run("status", "--root", str(tiny_repo), "--json").output)
    assert status["state"] == "enabled" and status["indexed"] is False


def test_status_states_and_lifecycle(tiny_repo: Path) -> None:
    root = str(tiny_repo)
    assert "not initialized" in run("status", "--root", root).output
    assert run("scan", "--root", root).exit_code == 1

    run("init", "--root", root, "--yes")
    data = json.loads(run("status", "--root", root, "--json").output)
    assert data["state"] == "enabled" and data["fresh"] is True

    assert run("pause", "--root", root).exit_code == 0
    assert json.loads(run("status", "--root", root, "--json").output)["state"] == "paused"
    assert run("resume", "--root", root).exit_code == 0
    assert run("disable", "--root", root).exit_code == 0
    data = json.loads(run("status", "--root", root, "--json").output)
    assert data["state"] == "not_enabled"
    assert data["state_label"] == "initialized · not enabled for you"
    assert run("pause", "--root", root).exit_code == 1  # can't pause what isn't enabled
    assert run("enable", "--root", root).exit_code == 0
    assert json.loads(run("status", "--root", root, "--json").output)["state"] == "enabled"


def test_teammate_repo_without_local_consent_is_untouched(tiny_repo: Path, tmp_path: Path) -> None:
    """A repo initialized by someone else: status reads, but writes nothing anywhere."""
    run("init", "--root", str(tiny_repo), "--yes")
    registry_path().unlink()  # simulate a different user on another machine
    before = snapshot(tiny_repo)
    result = run("status", "--root", str(tiny_repo))
    assert result.exit_code == 0
    assert "not enabled for you" in result.output
    assert snapshot(tiny_repo) == before
    assert not registry_path().exists()


def test_scan_full_and_json(tiny_repo: Path) -> None:
    run("init", "--root", str(tiny_repo), "--yes", "--no-scan")
    result = run("scan", "--root", str(tiny_repo), "--full", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output)["stats"]["symbols"] == 11
