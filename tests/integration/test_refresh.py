from __future__ import annotations

import json
from pathlib import Path

import pytest

from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan, update
from prism.narrator import refresh_commit, refresh_prepare


@pytest.fixture
def repo(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def test_prepare_offers_unwritten_sections(repo: Path) -> None:
    packet = refresh_prepare(repo)
    names = [p["section"] for p in packet["sections"]]
    assert names == ["purpose", "architecture", "conventions"]
    arch = packet["sections"][1]
    assert arch["token_limit"] == 220 and arch["current_text"] == ""
    assert arch["top_modules"][0]["id"] == "shop.money"


def test_prepare_for_stale_module_section(repo: Path) -> None:
    for i in range(5):
        (repo / "src" / "shop" / "pricing" / f"promo_{i}.py").write_text(
            f"def promo_{i}():\n    pass\n"
        )
    update(repo, lazy_rank=False)
    packet = refresh_prepare(repo, ["modules/shop.pricing"])
    section = packet["sections"][0]
    assert section["stale"] is True
    assert any("promo_" in c for c in section["changes"])
    assert "Public API" in section["module_facts"]


def test_commit_writes_narrative_and_resets_drift(repo: Path) -> None:
    text = "Small shop backend: prices carts, applies discounts, captures payment, exposes an orders API."
    result = refresh_commit(repo, "purpose", text)
    assert result["drift_reset"]
    agents = (repo / ".aicontext" / "AGENTS.md").read_text(encoding="utf-8")
    assert text in agents
    manifest = json.loads((repo / ".aicontext" / "manifest.json").read_text())
    assert manifest["drift"]["sections"]["purpose"]["score"] == 0
    assert "last_refresh" in manifest["drift"]["sections"]["purpose"]
    # A rescan regenerates facts but keeps the narrative.
    (repo / "src" / "shop" / "new_mod.py").write_text("def x():\n    pass\n")
    scan(repo)
    assert text in (repo / ".aicontext" / "AGENTS.md").read_text(encoding="utf-8")
    assert "purpose" not in [p["section"] for p in refresh_prepare(repo)["sections"]]


def test_commit_module_summary(repo: Path) -> None:
    refresh_commit(
        repo, "modules/shop.pricing", "Discount rules and their application to cart totals."
    )
    text = (repo / ".aicontext" / "modules" / "shop.pricing.md").read_text(encoding="utf-8")
    assert "Discount rules and their application" in text


@pytest.mark.parametrize(
    ("section", "text", "problem"),
    [
        ("purpose", "", "empty"),
        ("purpose", "word " * 200, "limit"),
        ("purpose", "ok <!-- prism:generated:facts -->", "markers"),
        ("purpose", "# Heading\ntext", "heading"),
        ("nonsense", "text", "unknown section"),
    ],
)
def test_commit_rejects_invalid_text(repo: Path, section: str, text: str, problem: str) -> None:
    before = (repo / ".aicontext" / "AGENTS.md").read_bytes()
    with pytest.raises(UserError, match=problem):
        refresh_commit(repo, section, text)
    assert (repo / ".aicontext" / "AGENTS.md").read_bytes() == before


def test_whole_brief_budget_is_enforced(repo: Path) -> None:
    refresh_commit(repo, "architecture", "Layered: api -> checkout -> pricing -> money. " * 16)
    agents = (repo / ".aicontext" / "AGENTS.md").read_text(encoding="utf-8")
    assert estimate_tokens(agents) <= 600
    with pytest.raises(UserError, match=r"AGENTS\.md would be"):
        refresh_commit(
            repo, "conventions", "Use Money for all amounts; never floats for cents. " * 11
        )


def test_top_modules_have_no_placeholder_and_commit_uses_validator(repo: Path) -> None:
    from prism.maintenance import doctor
    from prism.navigator.api import op_brief, op_module
    from prism.navigator.store import IndexStore
    from prism.writers.modules_md import NARRATIVE_PLACEHOLDER

    packet = refresh_prepare(repo, top=2)
    assert len(packet["sections"]) == 2
    assert all(section["section"].startswith("modules/") for section in packet["sections"])
    assert all(section["current_text"] == "" for section in packet["sections"])
    store = IndexStore.open(repo)
    try:
        assert NARRATIVE_PLACEHOLDER not in op_module(store, "shop.pricing")["text"]
        assert "Not written yet" not in op_brief(repo, full=True)["brief"]
    finally:
        store.close()
    ratio = next(check for check in doctor(repo) if check.name == "module narratives")
    assert ratio.detail.startswith("0/")
    refresh_commit(
        repo,
        packet["sections"][0]["section"],
        "Responsible for the listed pricing and currency entry points.",
    )
    ratio = next(check for check in doctor(repo) if check.name == "module narratives")
    assert ratio.detail.startswith("1/")


def test_refresh_top_cli(repo: Path) -> None:
    from typer.testing import CliRunner

    from prism.cli import app

    result = CliRunner().invoke(app, ["refresh", "--top", "1", "--root", str(repo)])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["sections"]) == 1
