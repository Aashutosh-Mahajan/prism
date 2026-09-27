from __future__ import annotations

from pathlib import Path

from prism.consent import RepoEntry, RepoState, get_entry, registry_path, repo_state, set_entry
from prism.consent.registry import load_registry


def test_registry_lives_under_config_home(_isolated_user_config: Path) -> None:
    assert registry_path().parent == _isolated_user_config


def test_roundtrip_with_awkward_paths(tmp_path: Path) -> None:
    root = tmp_path / "wéird päth's" / "repo"
    root.mkdir(parents=True)
    set_entry(root, RepoEntry("a" * 32, True, False))
    assert get_entry(root) == RepoEntry("a" * 32, True, False)
    set_entry(root, None)
    assert get_entry(root) is None


def test_states(tmp_path: Path) -> None:
    rid = "b" * 32
    assert repo_state(tmp_path, None) is RepoState.NOT_INITIALIZED
    assert repo_state(tmp_path, rid) is RepoState.NOT_ENABLED
    set_entry(tmp_path, RepoEntry(rid, True, False))
    assert repo_state(tmp_path, rid) is RepoState.ENABLED
    set_entry(tmp_path, RepoEntry(rid, True, True))
    assert repo_state(tmp_path, rid) is RepoState.PAUSED
    # A different repo id (repo re-initialized) invalidates the old consent.
    assert repo_state(tmp_path, "c" * 32) is RepoState.NOT_ENABLED


def test_corrupt_registry_reads_as_empty() -> None:
    registry_path().parent.mkdir(parents=True, exist_ok=True)
    registry_path().write_text("[[[ not toml")
    assert load_registry() == {}
