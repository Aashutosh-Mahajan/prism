from pathlib import Path

from prism.core.paths import find_repo_root


def test_nested_git_repo_without_index_does_not_inherit_parent_index(tmp_path: Path) -> None:
    (tmp_path / ".aicontext").mkdir()
    nested = tmp_path / "nested"
    (nested / ".git").mkdir(parents=True)
    source = nested / "src"
    source.mkdir()
    assert find_repo_root(source) == nested


def test_worktree_git_file_is_also_a_boundary(tmp_path: Path) -> None:
    (tmp_path / ".aicontext").mkdir()
    nested = tmp_path / "worktree"
    nested.mkdir()
    (nested / ".git").write_text("gitdir: elsewhere\n")
    assert find_repo_root(nested) == nested


def test_normal_subfolder_finds_its_parent_index(tmp_path: Path) -> None:
    (tmp_path / ".aicontext").mkdir()
    source = tmp_path / "src"
    source.mkdir()
    assert find_repo_root(source) == tmp_path
