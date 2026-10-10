"""Ranking feedback: edited files rank slightly higher, bounded, decaying, and switchable."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import feedback


@pytest.fixture
def enabled(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    feedback._cache.clear()
    return small_repo


def test_edits_raise_a_bounded_boost_that_decays(enabled: Path) -> None:
    now = 1_000_000.0
    for _ in range(4):
        feedback.record_edits(enabled, ["src/shop/cart.py"], now=now)
    boost = feedback.boosts(enabled, now=now)["src/shop/cart.py"]
    assert 0 < boost <= feedback.MAX_BOOST
    later = feedback.boosts(enabled, now=now + 120 * 86400)["src/shop/cart.py"]
    assert later < boost / 2


def test_one_edit_gives_a_small_boost_and_unknown_files_none(enabled: Path) -> None:
    feedback.record_edits(enabled, ["src/shop/a.py"], now=10.0)
    table = feedback.boosts(enabled, now=10.0)
    assert 0 < table["src/shop/a.py"] < feedback.MAX_BOOST
    assert "src/shop/b.py" not in table


def test_disabling_it_restores_the_unboosted_ranking(
    enabled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feedback.record_edits(enabled, ["src/shop/a.py"])
    assert feedback.boosts(enabled)
    monkeypatch.setenv("PRISM_FEEDBACK", "0")
    assert feedback.boosts(enabled) == {}
    feedback.record_edits(enabled, ["src/shop/zzz.py"])
    monkeypatch.delenv("PRISM_FEEDBACK")
    assert "src/shop/zzz.py" not in feedback.boosts(enabled)


def test_a_damaged_table_is_ignored(enabled: Path) -> None:
    feedback.record_edits(enabled, ["src/shop/a.py"])
    feedback._path(enabled).write_text("{not json", encoding="utf-8")
    feedback._cache.clear()
    assert feedback.boosts(enabled) == {}


def test_the_edit_hook_feeds_the_table(enabled: Path) -> None:
    import json

    from prism.hooks import post_edit

    target = enabled / "src" / "shop" / "utils.py"
    target.write_text(target.read_text(encoding="utf-8") + "\nX = 1\n", encoding="utf-8")
    post_edit(json.dumps({"cwd": str(enabled), "tool_input": {"file_path": str(target)}}))
    feedback._cache.clear()
    assert "src/shop/utils.py" in feedback.boosts(enabled)
