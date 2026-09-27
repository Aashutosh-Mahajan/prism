from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import jsonschema
import pytest

from prism.core.errors import UserError
from prism.lifecycle import apply_init, plan_init, scan
from prism.status import compute_status
from prism.writers.artifacts import ARTIFACTS

SCHEMAS = Path(__file__).parents[2] / "prism" / "schemas"
GOLDEN = Path(__file__).parents[1] / "golden"


def content_files(out: Path) -> dict[str, bytes]:
    """Every committed .aicontext file except the manifest (the only one with timestamps)."""
    return {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "manifest.json" and "cache" not in p.relative_to(out).parts
    }


def init_and_scan(repo: Path) -> Path:
    apply_init(plan_init(repo))
    scan(repo)
    return repo / ".aicontext"


def load(path: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture", ["tiny_repo", "small_repo"])
def test_artifacts_match_schemas(fixture: str, request: pytest.FixtureRequest) -> None:
    out = init_and_scan(request.getfixturevalue(fixture))
    for name in [*ARTIFACTS, "manifest.json"]:
        schema = load(SCHEMAS / name.replace(".json", ".schema.json"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(load(out / name), schema)


def test_scan_is_byte_deterministic_across_locations(tmp_path: Path) -> None:
    src = Path(__file__).parents[1] / "fixtures" / "repos" / "small"
    a = shutil.copytree(src, tmp_path / "a" / "small")
    b = shutil.copytree(src, tmp_path / "elsewhere" / "deeper" / "small")
    out_a, out_b = init_and_scan(a), init_and_scan(b)
    files_a = content_files(out_a)
    assert files_a == content_files(out_b)
    assert "modules/shop.pricing.md" in files_a
    scan(a)
    assert files_a == content_files(out_a)
    assert b"\r\n" not in files_a["symbols.json"]


def test_golden_tiny(tiny_repo: Path) -> None:
    out = init_and_scan(tiny_repo)
    golden = GOLDEN / "tiny"
    produced = content_files(out)
    if os.environ.get("PRISM_UPDATE_GOLDEN") == "1":
        shutil.rmtree(golden, ignore_errors=True)
        for name, data in produced.items():
            (golden / name).parent.mkdir(parents=True, exist_ok=True)
            (golden / name).write_bytes(data)
    expected = content_files(golden)
    assert sorted(produced) == sorted(expected)
    for name in expected:
        assert produced[name] == expected[name], (
            f"{name} differs from golden; rerun with PRISM_UPDATE_GOLDEN=1 if intended"
        )


def test_small_repo_facts(small_repo: Path) -> None:
    # Created here, not committed: the fixture's .gitignore would keep them out of git too.
    (small_repo / "generated").mkdir()
    (small_repo / "generated" / "big.py").write_text("def ignored():\n    pass\n")
    (small_repo / "server.log").write_text("debug output\n")
    out = init_and_scan(small_repo)
    symbols = {s["id"]: s for s in load(out / "symbols.json")["symbols"]}
    target = symbols["shop.pricing.discounts.apply_discount"]
    assert target["file"] == "src/shop/pricing/discounts.py"
    assert target["doc"] == "Apply the best eligible discount to an amount."
    assert "shop.checkout.cart.Cart.total" in target["called_by"]
    assert "shop.pricing.rules.eligible_rules" in target["calls"]
    # Ignored and non-source files never reach the index.
    manifest = load(out / "manifest.json")
    assert "generated/big.py" not in manifest["files"]
    assert "server.log" not in manifest["files"]
    assert manifest["files"]["scripts/deploy"]["language"] == "shell"
    assert manifest["files"]["src/shop/legacy.py"]["parse_error"].startswith("SyntaxError")
    assert manifest["stats"]["parse_errors"] == 1
    # The most depended-on module ranks first.
    modules = load(out / "dependency_graph.json")["modules"]
    top = max(modules, key=lambda m: m["rank"])
    assert top["id"] == "shop.money"


def test_scan_requires_init(tiny_repo: Path) -> None:
    with pytest.raises(UserError):
        scan(tiny_repo)
    assert not (tiny_repo / ".aicontext").exists()


def test_scan_preserves_manifest_identity(tiny_repo: Path) -> None:
    out = init_and_scan(tiny_repo)
    first = load(out / "manifest.json")
    scan(tiny_repo)
    second = load(out / "manifest.json")
    assert first["repo_id"] == second["repo_id"]
    assert first["created"] == second["created"]


def test_status_detects_changes(tiny_repo: Path) -> None:
    init_and_scan(tiny_repo)
    assert compute_status(tiny_repo).fresh
    (tiny_repo / "tinyshop" / "pricing.py").write_text("def changed():\n    pass\n")
    (tiny_repo / "tinyshop" / "new.py").write_text("x = 1\n")
    (tiny_repo / "tinyshop" / "cli.py").unlink()
    report = compute_status(tiny_repo)
    assert report.modified == ["tinyshop/pricing.py"]
    assert report.added == ["tinyshop/new.py"]
    assert report.deleted == ["tinyshop/cli.py"]
    scan(tiny_repo)
    assert compute_status(tiny_repo).fresh


def test_rescan_keeps_agent_narrative(tiny_repo: Path) -> None:
    out = init_and_scan(tiny_repo)
    agents = out / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    start = text.index("<!-- prism:narrative:purpose -->")
    end = text.index("<!-- /prism:narrative:purpose -->")
    agents.write_text(
        text[:start] + "<!-- prism:narrative:purpose -->\nPrices carts.\n" + text[end:],
        encoding="utf-8",
    )
    (tiny_repo / "tinyshop" / "extra.py").write_text("def extra():\n    pass\n")
    scan(tiny_repo)
    new = agents.read_text(encoding="utf-8")
    assert "Prices carts." in new
    assert "6 files" in new
