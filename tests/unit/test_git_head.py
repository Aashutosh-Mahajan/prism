"""Reading HEAD from `.git` must agree with `git rev-parse HEAD` without spawning git."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from prism.health import git_intel
from prism.health.git_intel import git_head

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


@pytest.fixture
def no_git_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object) -> None:
        raise AssertionError("git should not be spawned")

    monkeypatch.setattr(git_intel, "_git", fail)
    monkeypatch.delenv("GIT_DIR", raising=False)


def test_branch_loose_and_packed_refs(tmp_path: Path, no_git_cli: None) -> None:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text(SHA + "\n")
    assert git_head(tmp_path) == SHA
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text(f"# pack-refs with: peeled\n{OTHER} refs/heads/main\n")
    nested = tmp_path / "pkg" / "sub"
    nested.mkdir(parents=True)
    assert git_head(nested) == OTHER  # found from a subdirectory too


def test_detached_head_and_worktree_file(tmp_path: Path, no_git_cli: None) -> None:
    main = tmp_path / "main" / ".git"
    (main / "refs" / "heads").mkdir(parents=True)
    (main / "refs" / "heads" / "feature").write_text(SHA)
    wt_git = main / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/feature\n")
    (wt_git / "commondir").write_text("../..\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {wt_git}\n")
    assert git_head(worktree) == SHA
    (wt_git / "HEAD").write_text(OTHER + "\n")
    assert git_head(worktree) == OTHER


def test_not_a_repository_spawns_nothing(tmp_path: Path, no_git_cli: None) -> None:
    if git_intel._git_dir(tmp_path) is not None:
        pytest.skip("the temporary directory is inside a git repository")
    assert git_head(tmp_path) is None


def test_unusual_layout_falls_back_to_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/unborn\n")
    monkeypatch.setattr(git_intel, "_git", lambda root, *args: None)
    assert git_head(tmp_path) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_agrees_with_git_on_a_real_repository(tmp_path: Path) -> None:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    run("init", "-q")
    (tmp_path / "a.txt").write_text("a")
    run("add", "a.txt")
    run("commit", "-qm", "one")
    assert git_head(tmp_path) == run("rev-parse", "HEAD")
    run("pack-refs", "--all")
    assert git_head(tmp_path) == run("rev-parse", "HEAD")
    run("checkout", "-q", "--detach")
    assert git_head(tmp_path) == run("rev-parse", "HEAD")
