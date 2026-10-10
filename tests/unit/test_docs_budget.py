from pathlib import Path


def test_standing_context_budget_and_linked_specs() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 200
    assert (len(text) + 3) // 4 <= 4000
    for file in (root / "docs/spec").glob("*.md"):
        assert file.relative_to(root).as_posix() in text
    for name in ("prism/navigator/CLAUDE.md", "prism/integrations/CLAUDE.md", "viewer/CLAUDE.md"):
        assert len((root / name).read_text(encoding="utf-8").splitlines()) <= 120
