"""Experimental post-edit hints are bounded, opt-in and session-aware."""

import json
from pathlib import Path

from prism.core.tokens import estimate_tokens
from prism.hooks.edit_hints import post_edit_hint
from prism.lifecycle import apply_init, plan_init, scan, set_paused
from prism.writers.worklog import record_edits


def test_hints_require_opt_in_and_exclude_touched_dependents(small_repo: Path):
    apply_init(plan_init(small_repo))
    scan(small_repo)
    raw = json.dumps(
        {
            "cwd": str(small_repo),
            "session_id": "hint-session",
            "tool_input": {"file_path": "src/shop/pricing/discounts.py"},
        }
    )
    assert post_edit_hint(raw) == ""
    config = small_repo / "pyproject.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\n[tool.prism]\npost_edit_hints = true\n",
        encoding="utf-8",
    )
    hint = post_edit_hint(raw)
    assert "src/shop/checkout/cart.py" in hint
    assert "src/shop/pricing/discounts.py:" not in hint
    assert estimate_tokens(hint) <= 150
    record_edits(small_repo, "hint-session", [("src/shop/checkout/cart.py", "")])
    assert "src/shop/checkout/cart.py" not in post_edit_hint(raw)
    set_paused(small_repo, True)
    assert post_edit_hint(raw) == ""
