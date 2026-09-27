"""Incremental equivalence (CLAUDE.md 17): scan from scratch == scan + N x update.

Random but seeded edit sequences are applied to a copy of the small fixture.
After every step, `update` (with exact ranking) must produce exactly the same
`.aicontext/` content as a full scan of the same tree in a fresh copy.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan, update

FIXTURE = Path(__file__).parents[1] / "fixtures" / "repos" / "small"


def content(out: Path) -> dict[str, bytes]:
    return {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "manifest.json" and "cache" not in p.relative_to(out).parts
    }


def strip_ranks(files: dict[str, bytes]) -> dict[str, object]:
    """Structure only: drop every rank-derived value (for lazy-ranking comparisons)."""
    out: dict[str, object] = {}
    for name, data in files.items():
        if name == "symbols.json":
            out[name] = [
                {k: v for k, v in s.items() if k != "rank"} for s in json.loads(data)["symbols"]
            ]
        elif name == "call_graph.json" or name == "dependency_graph.json":
            out[name] = json.loads(data)["edges"]
    return out


def edit_add_function(root: Path, rng: random.Random) -> None:
    target = rng.choice(sorted((root / "src" / "shop").rglob("*.py")))
    n = rng.randrange(10_000)
    target.write_text(
        target.read_text(encoding="utf-8") + f"\n\ndef added_{n}(x):\n    return zero()\n",
        encoding="utf-8",
    )


def edit_new_module(root: Path, rng: random.Random) -> None:
    n = rng.randrange(10_000)
    (root / "src" / "shop" / f"extra_{n}.py").write_text(
        f'"""Extra {n}."""\n\nfrom shop.money import Money\n\n\ndef make_{n}() -> Money:\n    return Money({n})\n',
        encoding="utf-8",
    )


def edit_delete_module(root: Path, rng: random.Random) -> None:
    candidates = sorted((root / "src" / "shop").glob("extra_*.py")) or [
        root / "src" / "shop" / "utils.py"
    ]
    victim = rng.choice(candidates)
    if victim.exists():
        victim.unlink()


def edit_change_call(root: Path, rng: random.Random) -> None:
    cart = root / "src" / "shop" / "checkout" / "cart.py"
    text = cart.read_text(encoding="utf-8")
    if "apply_discount(self.subtotal()" in text:
        text = text.replace(
            "apply_discount(self.subtotal(), self.rules, coupon)", "self.subtotal()"
        )
    else:
        text = text.replace(
            "return self.subtotal()", "return apply_discount(self.subtotal(), self.rules, coupon)"
        )
    cart.write_text(text, encoding="utf-8")


def edit_rename(root: Path, rng: random.Random) -> None:
    rules = root / "src" / "shop" / "pricing" / "rules.py"
    text = rules.read_text(encoding="utf-8")
    old, new = (
        ("applies", "is_applicable") if "def applies" in text else ("is_applicable", "applies")
    )
    rules.write_text(text.replace(old, new), encoding="utf-8")


def edit_break_syntax(root: Path, rng: random.Random) -> None:
    legacy = root / "src" / "shop" / "legacy.py"
    fixed = "def legacy():\n    return 1\n"
    legacy.write_text(
        fixed if "broken" in legacy.read_text(encoding="utf-8") else "def broken(:\n",
        encoding="utf-8",
    )


EDITS = [
    edit_add_function,
    edit_new_module,
    edit_delete_module,
    edit_change_call,
    edit_rename,
    edit_break_syntax,
]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_scan_equals_scan_plus_updates(seed: int, tmp_path: Path) -> None:
    rng = random.Random(seed)
    work = shutil.copytree(FIXTURE, tmp_path / "work")
    apply_init(plan_init(work))
    scan(work)
    for step in range(6):
        rng.choice(EDITS)(work, rng)
        update(work, lazy_rank=False)  # may be skipped if the edit was a no-op
        fresh = tmp_path / f"fresh-{step}"
        shutil.copytree(work, fresh, ignore=shutil.ignore_patterns(".aicontext", ".gitignore"))
        apply_init(plan_init(fresh))
        scan(fresh, full=True)
        # Narrative regions are carried over, facts are regenerated: both copies start from scratch here.
        assert content(work / ".aicontext") == content(fresh / ".aicontext"), (
            f"diverged at step {step}"
        )


def test_lazy_ranking_keeps_structure_identical(tmp_path: Path) -> None:
    work = shutil.copytree(FIXTURE, tmp_path / "work")
    apply_init(plan_init(work))
    scan(work)
    edit_add_function(work, random.Random(7))
    result = update(work)  # lazy ranking
    assert result.manifest["rank_approx"] in (True, False)
    fresh = shutil.copytree(
        work, tmp_path / "fresh", ignore=shutil.ignore_patterns(".aicontext", ".gitignore")
    )
    apply_init(plan_init(fresh))
    scan(fresh, full=True)
    assert strip_ranks(content(work / ".aicontext")) == strip_ranks(content(fresh / ".aicontext"))
    scan(work)
    assert json.loads((work / ".aicontext" / "manifest.json").read_text())["rank_approx"] is False


def test_update_reparses_only_changed_files(tmp_path: Path) -> None:
    work = shutil.copytree(FIXTURE, tmp_path / "work")
    apply_init(plan_init(work))
    scan(work)
    assert update(work).skipped
    utils = work / "src" / "shop" / "utils.py"
    utils.write_text(utils.read_text(encoding="utf-8") + "\n# comment\n", encoding="utf-8")
    result = update(work, files=["src/shop/utils.py"])
    assert result.changed == ("src/shop/utils.py",)
    assert result.reparsed == 1


def _drift(work: Path) -> dict[str, dict[str, object]]:
    manifest = json.loads((work / ".aicontext" / "manifest.json").read_text())
    return manifest["drift"]["sections"]


@pytest.fixture
def drift_repo(tmp_path: Path) -> Path:
    work = shutil.copytree(FIXTURE, tmp_path / "work")
    apply_init(plan_init(work))
    scan(work)
    assert _drift(work) == {}
    return work


def test_formatting_and_comment_changes_score_zero(drift_repo: Path) -> None:
    cart = drift_repo / "src" / "shop" / "checkout" / "cart.py"
    text = cart.read_text(encoding="utf-8")
    cart.write_text(
        "# reformatted\n" + text.replace("    def add", "\n    # note\n    def add"),
        encoding="utf-8",
    )
    body = drift_repo / "src" / "shop" / "utils.py"
    body.write_text(
        body.read_text(encoding="utf-8").replace("sort_keys=True", "sort_keys=False"),
        encoding="utf-8",
    )
    update(drift_repo, lazy_rank=False)
    assert all(v["score"] == 0 for v in _drift(drift_repo).values())


@pytest.mark.parametrize(
    ("edit", "section", "expected"),
    [
        (
            lambda r: (r / "src/shop/newpkg.py").write_text("def thing():\n    pass\n"),
            "architecture",
            5,
        ),
        (
            lambda r: (r / "src/shop/money.py").write_text(
                (r / "src/shop/money.py")
                .read_text()
                .replace("def zero() -> Money:", "def zero(n: int = 0) -> Money:")
            ),
            "modules/shop",
            2,
        ),
        (
            lambda r: (r / "src/shop/config.py").write_text(
                (r / "src/shop/config.py").read_text()
                + '\nTIMEOUT = os.environ.get("SHOP_TIMEOUT")\n'
            ),
            "architecture",
            3,
        ),
    ],
)
def test_weighted_changes(drift_repo: Path, edit: object, section: str, expected: int) -> None:
    edit(drift_repo)  # type: ignore[operator]
    update(drift_repo, lazy_rank=False)
    sections = _drift(drift_repo)
    assert sections[section]["score"] >= expected
    assert sections[section]["changes"]


def test_accumulated_drift_marks_sections_stale(drift_repo: Path) -> None:
    for i in range(2):
        (drift_repo / "src" / "shop" / f"feature_{i}.py").write_text(
            f"def feature_{i}():\n    pass\n"
        )
        update(drift_repo, lazy_rank=False)
    arch = _drift(drift_repo)["architecture"]
    assert arch["score"] >= 10 and arch["stale"] is True
