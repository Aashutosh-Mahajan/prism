"""Fast entry points preserve output, validation, consent and hook deadlines."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import daemon
from prism.taskfast import try_fast, try_find


def test_cold_find_and_task_match_cli_without_starting_find_daemon(
    small_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    monkeypatch.setenv("PRISM_DAEMON", "0")
    for command, operation, query in (
        ("find", try_find, "apply_discount"),
        ("task", try_fast, "where is apply_discount implemented"),
    ):
        args = [query, "--root", str(small_repo), "--json"]
        expected = CliRunner().invoke(app, [command, *args])
        assert expected.exit_code == 0
        assert operation(args)
        assert json.loads(capsys.readouterr().out) == json.loads(expected.output)
    assert daemon._read_info(small_repo) is None
    assert not try_find(["--help"])
    assert not try_fast(["query", "--budget", "127"])
    assert not try_find(["query", "--budget", "not-a-number"])


def test_expired_hook_request_does_not_retrieve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("expired hook was executed")

    monkeypatch.setattr("prism.hooks.prompt._retrieve", unexpected)
    assert daemon._handle(
        SimpleNamespace(root=tmp_path), {"op": "hook-prompt", "deadline": time.time() - 1}
    ) == {"ok": True, "text": ""}


def test_hook_result_after_deadline_is_not_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def delayed(root, prompt, session, budget, abandoned, inline_build):
        assert abandoned.wait(1)
        return "late source"

    monkeypatch.setattr("prism.hooks.prompt._retrieve", delayed)
    result = daemon._handle(
        SimpleNamespace(root=tmp_path),
        {
            "op": "hook-prompt",
            "query": "query",
            "session": "s",
            "budget": 1200,
            "deadline": time.time() + 0.02,
        },
    )
    assert result == {"ok": True, "text": ""}


def test_embedded_hook_preserves_output_and_never_exits(small_repo, monkeypatch):
    from prism.hooks import entry, runner

    apply_init(plan_init(small_repo))
    scan(small_repo)
    monkeypatch.setattr(runner, "session_start", lambda raw: "session evidence")
    monkeypatch.setattr(entry, "hard_exit", lambda: pytest.fail("embedded hook exited"))
    reply = daemon._handle(
        SimpleNamespace(root=small_repo),
        {
            "op": "hook",
            "name": "session-start",
            "args": [],
            "raw": json.dumps({"cwd": str(small_repo)}),
        },
    )
    assert reply == {"ok": True, "text": "session evidence\n"}
    assert daemon._handle(
        SimpleNamespace(root=small_repo),
        {"op": "hook", "name": "session-start", "raw": json.dumps({"cwd": str(small_repo.parent)})},
    ) == {"ok": False}
