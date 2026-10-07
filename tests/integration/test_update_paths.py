"""`prism update` accepts several changed files in every spelling agents use."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.lifecycle import apply_init, plan_init, scan
from prism.status import compute_status

runner = CliRunner()

EDITED = ("src/shop/pricing/discounts.py", "src/shop/money.py", "src/shop/utils.py")


@pytest.fixture
def repo(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def _touch_all(repo: Path) -> None:
    for rel in EDITED:
        path = repo / rel
        path.write_text(path.read_text() + "\n# edited by the agent\n")


@pytest.mark.parametrize(
    "spelling",
    [
        ["update", *EDITED],  # positional paths
        ["update", "--files", *EDITED],  # the form the benchmark agent used, which used to fail
        ["update", *[x for rel in EDITED for x in ("--files", rel)]],  # repeated flag
        ["update", EDITED[0], "--files", EDITED[1], EDITED[2]],  # mixed
    ],
)
def test_every_spelling_updates_all_files(repo: Path, spelling: list[str]) -> None:
    _touch_all(repo)
    assert compute_status(repo).modified  # the index is stale before the update
    result = runner.invoke(app, [*spelling, "--root", str(repo), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert sorted(data["changed"]) == sorted(EDITED)
    assert compute_status(repo).fresh


def test_update_without_paths_still_discovers_changes(repo: Path) -> None:
    _touch_all(repo)
    result = runner.invoke(app, ["update", "--root", str(repo), "--json"])
    assert result.exit_code == 0, result.output
    assert sorted(json.loads(result.output)["changed"]) == sorted(EDITED)
