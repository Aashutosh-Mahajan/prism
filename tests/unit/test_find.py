"""`prism find`: several searches in one call, exact lines, budgeted and ranked."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.find import render_find, run_find
from prism.navigator.store import IndexStore


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {
        "pyproject.toml": "[project]\nname='x'\n",
        "pkg/a.py": "def apply_discount(x):\n    return x - 1\n\n# TODO: coupon handling\n",
        "pkg/b.py": "from pkg.a import apply_discount\n\nprint(apply_discount(3))  # coupon\n",
        "tests/test_a.py": "from pkg.a import apply_discount\n\ndef test_it():\n    assert apply_discount(2) == 1\n",
        "archive/old/c.py": "def apply_discount(x):\n    return x\n",
        "data/messages.json": '{"coupon": "Coupon applied"}\n',
        "pkg/migrations/0001_x.py": "# apply_discount mention\n",
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    apply_init(plan_init(tmp_path))
    scan(tmp_path)
    return tmp_path


def find(repo: Path, *patterns: str, **kwargs: object) -> dict:
    store = IndexStore.open(repo)
    try:
        return run_find(store, list(patterns), **kwargs)  # type: ignore[arg-type]
    finally:
        store.close()


def test_several_patterns_in_one_call_with_exact_lines(repo: Path) -> None:
    pack = find(repo, "apply_discount", "coupon", ignore_case=True)
    by = {r["pattern"]: r for r in pack["results"]}
    assert by["apply_discount"]["total"] == 7 and by["coupon"]["total"] == 3
    assert by["apply_discount"]["complete"]
    text = render_find(pack)
    assert "pkg/b.py" in text and "    3: print(apply_discount(3)) # coupon" in text
    assert "data/messages.json" in text  # text and data files are searched too


def test_application_code_is_listed_before_tests_archives_and_migrations(repo: Path) -> None:
    files = [m["file"] for m in find(repo, "apply_discount")["results"][0]["matches"]]
    assert files[:2] == ["pkg/a.py", "pkg/b.py"]
    assert set(files[2:]) == {"tests/test_a.py", "archive/old/c.py", "pkg/migrations/0001_x.py"}


def test_glob_and_regex_narrow_the_search(repo: Path) -> None:
    pack = find(repo, r"apply_\w+\(", regex=True, globs=["pkg/*.py"])
    assert {m["file"] for m in pack["results"][0]["matches"]} == {"pkg/a.py", "pkg/b.py"}


def test_the_result_stays_within_its_budget_and_says_what_was_cut(repo: Path) -> None:
    pack = find(repo, "apply_discount", "coupon", budget=128)
    text = render_find(pack)
    assert estimate_tokens(text) <= 128
    assert pack["omitted"] > 0 and "omitted" in text


def test_bad_input_is_a_clear_error(repo: Path) -> None:
    with pytest.raises(UserError):
        find(repo)
    with pytest.raises(UserError, match="regular expression"):
        find(repo, "(", regex=True)
    with pytest.raises(UserError, match="at most"):
        find(repo, *[f"p{i}" for i in range(9)])


def test_the_command_does_not_expand_wildcards_itself(repo: Path) -> None:
    result = CliRunner().invoke(
        app, ["find", "apply_discount", "--root", str(repo), "--glob", "pkg/*.py", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert '"archive/old/c.py"' not in result.output
