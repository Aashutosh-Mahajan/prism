from pathlib import Path
from types import SimpleNamespace

import pytest

from prism.consent import RepoState
from prism.navigator import freshness
from prism.navigator.api import _with_freshness


def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(freshness, "load_manifest", lambda root: {"last_scan": "yes"})
    monkeypatch.setattr(freshness, "repo_state", lambda *args: RepoState.ENABLED)


def test_change_limit_is_not_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    enabled(monkeypatch)
    monkeypatch.setattr(freshness, "working_tree_changes", lambda *args: (["new.py"], [], []))
    state = freshness.refresh_index(tmp_path, max_files=0)
    assert state.state == "limited" and not state.complete and state.changed == 1
    assert freshness.refresh_if_stale(tmp_path, max_files=0) == 0


def test_failure_reason_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    enabled(monkeypatch)

    def fail(*args):
        raise PermissionError("private path must not leak")

    monkeypatch.setattr(freshness, "working_tree_changes", fail)
    state = freshness.refresh_index(tmp_path)
    assert state.reason == "PermissionError" and not state.complete


def test_incomplete_refresh_revokes_patch_and_exhaustive_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enabled(monkeypatch)
    monkeypatch.setattr(freshness, "working_tree_changes", lambda *args: (["new.py"], [], []))
    freshness.refresh_index(tmp_path, max_files=0)
    pack = {
        "intent": "edit",
        "confidence": "high",
        "sufficient": True,
        "next": "edit",
        "blocks": [],
        "stale_sources": 0,
        "budget": {"requested": 2000, "used_est": 0},
        "patch": {"path": "patch.diff"},
        "assessment": {"basis": "checked_mechanical_patch", "unresolved": [], "calibrated": False},
        "literals": [
            {"text": "x", "kind": "quoted", "total": 1, "complete": True, "occurrences": []}
        ],
    }
    result = _with_freshness(SimpleNamespace(root=tmp_path), pack)
    assert not result["sufficient"] and "patch" not in result
    assert not result["literals"][0]["complete"]
    assert result["assessment"]["basis"] == "candidates_only"
    assert "search_scope" in result["assessment"]["unresolved"]
    assert result["budget"]["used_est"] <= 2000


def test_verification_does_not_turn_incomplete_absence_into_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prism.navigator import api

    monkeypatch.setattr(
        api,
        "op_task",
        lambda *args, **kwargs: {
            "blocks": [],
            "confidence": "low",
            "stale_sources": 0,
            "search_limited": True,
            "budget": {"requested": 2000, "used_est": 0},
        },
    )
    result = api._verify(None, "replace old value", 2000, None)
    assert not result["sufficient"]
    assert result["search_limited"]
    assert "incomplete" in result["next"]
