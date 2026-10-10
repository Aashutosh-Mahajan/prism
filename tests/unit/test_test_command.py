"""The packet names the exact command that runs the tests it lists."""

from __future__ import annotations

from pathlib import Path

from prism.navigator.test_command import _tests, run_command


def fresh(root: Path) -> Path:
    _tests.cache_clear()
    return root


def test_pytest_project_gets_the_listed_files(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    root = fresh(tmp_path)
    assert (
        run_command(root, ["tests/test_a.py", "tests/test_b.py"])
        == "python -m pytest -q tests/test_a.py tests/test_b.py"
    )


def test_a_subproject_command_is_run_from_its_directory(tmp_path: Path) -> None:
    sub = tmp_path / "backend"
    sub.mkdir()
    (sub / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    root = fresh(tmp_path)
    assert (
        run_command(root, ["backend/tests/test_a.py"])
        == "cd backend && python -m pytest -q tests/test_a.py"
    )


def test_runners_that_take_no_file_arguments_get_the_plain_command(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    root = fresh(tmp_path)
    assert run_command(root, ["app/tests.py"]) == "python manage.py test"


def test_no_known_toolchain_or_no_tests_gives_nothing(tmp_path: Path) -> None:
    root = fresh(tmp_path)
    assert run_command(root, ["tests/test_a.py"]) is None
    assert run_command(root, []) is None


def test_unrelated_tests_are_not_sliced_into_a_subproject(tmp_path: Path) -> None:
    sub = tmp_path / "backend"
    sub.mkdir()
    (sub / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert run_command(fresh(tmp_path), ["frontend/tests/test_api.py"]) is None


def test_test_paths_with_spaces_are_quoted(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert run_command(fresh(tmp_path), ["tests/test api.py"]) == (
        "python -m pytest -q 'tests/test api.py'"
    )
