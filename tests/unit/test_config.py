from __future__ import annotations

from pathlib import Path

import pytest

from prism.config import PrismConfig, load_config
from prism.core.errors import UserError


def test_defaults_without_config(tmp_path: Path) -> None:
    assert load_config(tmp_path) == PrismConfig()


def test_pyproject_tool_prism(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.prism]\nignore = ["gen/"]\nmax_file_size = 10\nsource_roots = ["lib"]\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.ignore == ("gen/",)
    assert cfg.max_file_size == 10
    assert cfg.source_roots == ("lib",)


def test_prism_toml_wins_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.prism]\nignore = ["a"]\n')
    (tmp_path / "prism.toml").write_text('ignore = ["b"]\n')
    assert load_config(tmp_path).ignore == ("b",)


@pytest.mark.parametrize(
    "body", ['ignore = "notalist"', "max_file_size = -1", "drift_threshold = 0", "ignore = ["]
)
def test_invalid_config_is_a_user_error(tmp_path: Path, body: str) -> None:
    (tmp_path / "prism.toml").write_text(body + "\n")
    with pytest.raises(UserError):
        load_config(tmp_path)
