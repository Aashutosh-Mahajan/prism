from __future__ import annotations

from pathlib import Path

from prism.core.markers import parse_regions, render_region
from prism.pipeline import build_index
from prism.writers.agents_md import (
    BRIEF_TOKEN_LIMIT,
    NARRATIVE_PLACEHOLDER,
    brief_tokens,
    render_agents_md,
)
from prism.writers.json_writer import dumps, write_json, write_text


def test_dumps_is_sorted_and_lf(tmp_path: Path) -> None:
    text = dumps({"b": 1, "a": {"d": [1, 2], "c": "é"}})
    assert text.index('"a"') < text.index('"b"')
    assert "\r" not in text and text.endswith("\n")
    assert "é" in text


def test_write_skips_identical_content(tmp_path: Path) -> None:
    path = tmp_path / "x" / "f.json"
    assert write_json(path, {"a": 1}) is True
    assert write_json(path, {"a": 1}) is False
    assert write_text(path, "other\n") is True
    assert path.read_bytes() == b"other\n"
    assert not list(path.parent.glob("*.tmp"))


def test_regions_roundtrip() -> None:
    text = "intro\n" + render_region("narrative", "purpose", "Line one.\nLine two.") + "\n"
    regions = parse_regions(text.replace("\n", "\r\n"))
    assert regions[("narrative", "purpose")].body == "Line one.\nLine two."


def test_agents_md_preserves_narrative_and_rewrites_generated(tiny_repo: Path) -> None:
    index = build_index(tiny_repo)
    first = render_agents_md(index)
    assert first.count(NARRATIVE_PLACEHOLDER) == 3
    edited = first.replace(
        "<!-- prism:narrative:purpose -->\n" + NARRATIVE_PLACEHOLDER,
        "<!-- prism:narrative:purpose -->\nA tiny shop that prices carts.",
    ).replace("- Languages:", "- HAND EDIT Languages:")
    second = render_agents_md(index, edited)
    assert "A tiny shop that prices carts." in second
    assert "HAND EDIT" not in second  # generated regions are owned by PRISM
    assert second.count(NARRATIVE_PLACEHOLDER) == 2
    assert render_agents_md(index, second) == second


def test_agents_md_skeleton_within_budget(small_repo: Path) -> None:
    text = render_agents_md(build_index(small_repo))
    assert brief_tokens(text) <= BRIEF_TOKEN_LIMIT
    assert "# smallshop — Agent Brief" in text
    assert "`shop-api` (src/shop/api/app.py)" in text
    assert text.count("src/shop/api/app.py") == 1  # entry points deduped per file


def test_brief_ignores_test_only_dependencies_and_entry_points(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import requests\n\ndef main():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text(
        'import pytest\n\nif __name__ == "__main__":\n    pytest.main()\n', encoding="utf-8"
    )
    text = render_agents_md(build_index(tmp_path))
    assert "- Key dependencies: requests" in text
    assert "pytest" not in text.split("- Commands:")[0]
    assert "tests/test_app.py" not in text
