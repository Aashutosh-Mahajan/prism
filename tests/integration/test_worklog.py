"""The work log: what one session asked, edited and noted reaches the next one, briefly."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.consent import registry_path
from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.hooks import post_edit, session_start
from prism.hooks.runner import edit_anchors
from prism.lifecycle import apply_init, plan_init, scan, set_paused
from prism.mcp.server import PrismTools, enabled_tools
from prism.navigator import api
from prism.navigator.recall import last_session_brief, recall, related_history
from prism.navigator.store import IndexStore
from prism.writers import worklog


def payload(root: Path, **extra: object) -> str:
    return json.dumps({"cwd": str(root), "hook_event_name": "x", **extra})


@pytest.fixture
def enabled(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def _edit_discounts(root: Path, session: str) -> None:
    path = root / "src" / "shop" / "pricing" / "discounts.py"
    text = path.read_text(encoding="utf-8")
    anchor = "        best = max(best, coupon)"
    assert anchor in text
    post_edit(
        payload(
            root,
            session_id=session,
            tool_name="Edit",
            tool_input={"file_path": str(path), "old_string": anchor, "new_string": anchor},
        )
    )


def test_previous_session_is_summarised_at_the_next_start(enabled: Path) -> None:
    worklog.record_request(
        enabled, "s1", "the discount is applied twice when a coupon and a sale overlap"
    )
    _edit_discounts(enabled, "s1")
    worklog.record_note(
        enabled, "s1", "coupon now applied after the sale; docs still say otherwise"
    )

    text = session_start(payload(enabled, session_id="s2"))
    assert "Last session (just now):" in text
    assert 'Asked: "the discount is applied twice' in text
    assert "src/shop/pricing/discounts.py (apply_discount)" in text
    assert "Note: coupon now applied after the sale" in text
    summary = text.split("Last session", 1)[1]
    assert estimate_tokens(summary) <= 140

    # The session's own log is not offered back to it.
    assert "Last session" not in session_start(payload(enabled, session_id="s1"))


def test_summary_prefers_a_session_that_changed_code(enabled: Path) -> None:
    _edit_discounts(enabled, "hooks-session")
    time.sleep(0.05)
    worklog.record_focus(enabled, "mcp-session", ["shop.money.Money"])
    brief = last_session_brief(enabled, current="new")
    assert "discounts.py" in brief and "Money" not in brief


def test_nothing_is_logged_without_consent_or_when_paused(enabled: Path) -> None:
    set_paused(enabled, True)
    _edit_discounts(enabled, "s1")
    assert not list(worklog.worklog_dir(enabled).glob("*.jsonl"))
    set_paused(enabled, False)
    registry_path().unlink()
    _edit_discounts(enabled, "s1")
    assert not list(worklog.worklog_dir(enabled).glob("*.jsonl"))


def test_worklog_can_be_turned_off(enabled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_WORKLOG", "0")
    worklog.record_request(enabled, "s1", "anything at all")
    _edit_discounts(enabled, "s1")
    assert not list(worklog.worklog_dir(enabled).glob("*.jsonl"))


def test_torn_lines_and_old_logs_are_tolerated(enabled: Path) -> None:
    worklog.record_note(enabled, "s1", "first note")
    path = next(worklog.worklog_dir(enabled).glob("*.jsonl"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"type": "note", "text": "half')
    assert [s.notes for s in worklog.sessions(enabled)] == [["first note"]]
    old = time.time() - (worklog.RETENTION_DAYS + 1) * 86400
    os.utime(path, (old, old))
    worklog.prune(enabled)
    assert not path.exists()


def test_note_validation() -> None:
    root = Path(".")
    with pytest.raises(UserError):
        worklog.record_note(root, "s", "   ")
    with pytest.raises(UserError):
        worklog.record_note(root, "s", "x" * 601)


def test_edit_anchors_cover_each_agent_shape(tmp_path: Path) -> None:
    claude = {
        "tool_input": {"file_path": "a.py", "old_string": "x", "new_string": "\n  def run(self):\n"}
    }
    assert edit_anchors(claude) == {"a.py": "def run(self):"}
    multi = {
        "tool_input": {
            "file_path": "a.py",
            "edits": [{"new_string": ""}, {"new_string": "y = compute()"}],
        }
    }
    assert edit_anchors(multi) == {"a.py": "y = compute()"}
    cursor = {"file_path": "b.ts", "edits": [{"old_string": "a", "new_string": "const total = 1"}]}
    assert edit_anchors(cursor) == {"b.ts": "const total = 1"}
    patch = (
        "*** Begin Patch\n*** Update File: c.py\n@@\n-old = 1\n+new_value = 2\n"
        "*** Add File: d.py\n+def made():\n*** End Patch"
    )
    codex = {"tool_input": {"command": ["apply_patch", patch]}}
    assert edit_anchors(codex) == {"c.py": "new_value = 2", "d.py": "def made():"}
    write = {"tool_input": {"file_path": "e.py", "content": "print(1)"}}
    assert edit_anchors(write) == {"e.py": ""}


def test_task_answers_mention_earlier_work_on_the_same_code(enabled: Path) -> None:
    worklog.record_request(enabled, "old", "make coupons stack with sales")
    _edit_discounts(enabled, "old")
    worklog.record_note(enabled, "old", "stacking is behind the coupon_stack setting")
    store = IndexStore.open(enabled)
    try:
        pack = api.op_task(store, "apply_discount", 2000, session="current")
        assert pack["history"] and "edited src/shop/pricing/discounts.py" in pack["history"][0]
        assert "coupon_stack setting" in pack["history"][0]
        assert pack["budget"]["used_est"] <= 2000
        # The session that did the work is not told about itself; a tight budget drops it.
        assert "history" not in api.op_task(store, "apply_discount", 2000, session="old")
        tight = api.op_task(store, "apply_discount", 160, session="current")
        assert tight["budget"]["used_est"] <= 160
        # Cached packets never carry time-relative history.
        assert "history" not in api.op_task(store, "apply_discount", 2000, session="old")
    finally:
        store.close()
    assert related_history(enabled, set(), set()) == []


def test_recall_and_note_from_cli_and_mcp(enabled: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["note", "--root", str(enabled), "--session", "cli", "renamed Cart.total; update docs"]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["recall", "--root", str(enabled), "docs"])
    assert result.exit_code == 0 and "renamed Cart.total" in result.output
    data = json.loads(runner.invoke(app, ["recall", "--root", str(enabled), "--json"]).output)
    assert data["sessions"][0]["notes"] == ["renamed Cart.total; update docs"]
    assert recall(enabled, "nothing-matches-this")["sessions"] == []

    assert "prism_recall" in enabled_tools(enabled, "full")
    assert "prism_recall" not in enabled_tools(enabled)  # lean profile stays small
    tools = PrismTools(enabled)
    assert tools.prism_note("left the old endpoint in place")["recorded"]
    assert tools.prism_recall()["sessions"][0]["notes"] == ["renamed Cart.total; update docs"]
    assert tools.prism_note("")["error"]
