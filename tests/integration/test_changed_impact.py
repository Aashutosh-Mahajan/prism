from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from typer.testing import CliRunner

from prism.cli import app
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.changed_impact import changed_impact, diff_ranges
from prism.navigator.store import IndexStore


def git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=disabled-hooks",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_staged_and_unstaged_impact_is_read_only(small_repo: Path) -> None:
    git(small_repo, "init", "-q")
    git(small_repo, "add", ".")
    git(small_repo, "commit", "--no-gpg-sign", "-qm", "baseline")
    apply_init(plan_init(small_repo))
    scan(small_repo)
    discount = small_repo / "src/shop/pricing/discounts.py"
    discount.write_text(
        discount.read_text(encoding="utf-8").replace("1 - best", "1 - min(best, 1)"),
        encoding="utf-8",
    )
    git(small_repo, "add", str(discount))
    money = small_repo / "src/shop/money.py"
    money.write_text(
        money.read_text(encoding="utf-8").replace("return Money(0)", "return Money(1)"),
        encoding="utf-8",
    )
    before = {
        path: path.read_bytes()
        for path in (discount, money, small_repo / ".aicontext/manifest.json")
    }
    store = IndexStore.open(small_repo)
    try:
        started = time.perf_counter()
        packet = changed_impact(store)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5
        changed = {row["symbol"]: row for row in packet["changed"]}
        assert "shop.pricing.discounts.apply_discount" in changed
        assert "shop.money.zero" in changed
        assert (
            "shop.checkout.cart.Cart.total"
            in changed["shop.pricing.discounts.apply_discount"]["callers"]
        )
        assert changed["shop.pricing.discounts.apply_discount"]["tests"]
        from prism.core.tokens import estimate_tokens

        for budget in (128, 256, 512):
            limited = changed_impact(store, budget)
            assert estimate_tokens(json.dumps(limited, separators=(",", ":"))) <= budget
    finally:
        store.close()
    assert before == {path: path.read_bytes() for path in before}
    result = CliRunner().invoke(app, ["impact", "--changed", "--json", "--root", str(small_repo)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["symbols_total"] >= 2


def test_diff_deletions_insertions_and_renamed_paths() -> None:
    patch = "--- a/old.py\n+++ b/new.py\n@@ -10,0 +11,2 @@\n--- a/gone.py\n+++ /dev/null\n@@ -3,4 +0,0 @@\n"
    assert diff_ranges(patch) == {"old.py": [(10, 10)], "new.py": [(11, 12)], "gone.py": [(3, 6)]}
