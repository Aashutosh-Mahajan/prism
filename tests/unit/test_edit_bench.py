"""The edit benchmark's own machinery: preparing sessions, scoring edits, measuring transcripts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.benchmarks import edit_bench

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")

FIXTURE = Path(__file__).parents[1] / "fixtures" / "repos" / "webapp"
TASKS = Path(__file__).parents[1] / "benchmarks" / "tasks" / "webapp_edits.json"


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("bench") / "run"
    edit_bench.prepare(FIXTURE, TASKS, out)
    return out


def apply_reference_solutions(out: Path, arm: str) -> None:
    def sub(rel: str, old: str, new: str, task: str) -> None:
        path = out / task / arm / rel
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    sub("backend/core/models.py", "LIFETIME_MINUTES = 10", "LIFETIME_MINUTES = 15", "t1-lifetime")
    for page in ("VerifyEmailPage", "ForgotPasswordPage"):
        sub(
            f"frontend/src/pages/auth/{page}.tsx",
            "expires in 10 minutes",
            "expires in 15 minutes",
            "t1-lifetime",
        )
    sub(
        "backend/core/analytics.py",
        '        out[key] = {"value": current.get(key), "previous": prev, "kind": kind}',
        "        value = current.get(key)\n"
        "        pct = None\n"
        "        if prev not in (None, 0) and value is not None:\n"
        "            pct = round((value - prev) / prev * 100, 1)\n"
        '        out[key] = {"value": value, "previous": prev, "kind": kind, "change_pct": pct}',
        "t2-change-pct",
    )
    sub(
        "frontend/src/api/auth.ts",
        "    data?.detail ||\n",
        "    data?.detail ||\n    (typeof data?.error?.message === 'string' ? data.error.message : '') ||\n",
        "t3-server-message",
    )


def test_prepare_builds_isolated_copies_and_prompts(prepared: Path) -> None:
    for task in ("t1-lifetime", "t2-change-pct", "t3-server-message"):
        assert not (prepared / task / "without" / ".aicontext").exists()
        assert (prepared / task / "tool" / ".aicontext" / "manifest.json").is_file()
        assert (prepared / task / "hook" / ".aicontext" / "manifest.json").is_file()
    plain = (prepared / "prompts" / "t1-lifetime-without.txt").read_text(encoding="utf-8")
    tool = (prepared / "prompts" / "t1-lifetime-tool.txt").read_text(encoding="utf-8")
    hook = (prepared / "prompts" / "t1-lifetime-hook.txt").read_text(encoding="utf-8")
    assert "prism task" not in plain and "Do not use any tool called `prism`" in plain
    assert "SESSION CONTEXT" in tool and 'prism task "<request>"' in tool
    assert "ADDITIONAL CONTEXT" not in tool
    assert "ADDITIONAL CONTEXT" in hook and 'Literal "10 minutes"' in hook
    assert plain.splitlines()[-1].startswith("FINAL ANSWER")
    # The same request, word for word, in every arm.
    request = json.loads(TASKS.read_text(encoding="utf-8"))[0]["request"]
    assert request in plain and request in tool and request in hook


def test_unedited_copies_fail_and_reference_solutions_pass(prepared: Path) -> None:
    before = edit_bench.verify(prepared)
    assert all(row["passed"] < row["total"] for row in before.values())
    apply_reference_solutions(prepared, "tool")
    after = edit_bench.verify(prepared)
    for task in ("t1-lifetime", "t2-change-pct", "t3-server-message"):
        row = after[f"{task}/tool"]
        assert row["passed"] == row["total"] and not row["failed"], (task, row["failed"])
        assert after[f"{task}/without"]["passed"] < after[f"{task}/without"]["total"]
    assert edit_bench.changed_files(prepared / "t1-lifetime" / "tool") == [
        "backend/core/models.py",
        "frontend/src/pages/auth/ForgotPasswordPage.tsx",
        "frontend/src/pages/auth/VerifyEmailPage.tsx",
    ]


def test_a_wrong_edit_is_caught(prepared: Path) -> None:
    path = prepared / "t2-change-pct" / "hook" / "backend/core/analytics.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '        out[key] = {"value": current.get(key), "previous": prev, "kind": kind}',
            '        out[key] = {"value": current.get(key), "previous": prev, "kind": kind,'
            ' "change_pct": 0}',
        ),
        encoding="utf-8",
    )
    row = edit_bench.verify(prepared)["t2-change-pct/hook"]
    assert row["failed"] and any("change_pct" in f for f in row["failed"])


def test_transcripts_are_measured_without_double_counting(tmp_path: Path) -> None:
    def turn(
        msg_id: str,
        fresh: int,
        write: int,
        read: int,
        tool: str | None = None,
        at: str = "2026-01-01T00:00:00Z",
    ) -> str:
        content: list[dict[str, object]] = []
        if tool:
            content.append({"type": "tool_use", "name": "Bash", "input": {"command": tool}})
        usage = {
            "input_tokens": fresh,
            "cache_creation_input_tokens": write,
            "cache_read_input_tokens": read,
        }
        return json.dumps(
            {
                "type": "assistant",
                "timestamp": at,
                "message": {"id": msg_id, "usage": usage, "content": content},
            }
        )

    result = json.dumps(
        {
            "type": "user",
            "timestamp": "2026-01-01T00:00:10Z",
            "message": {"content": [{"type": "tool_result", "content": "x" * 400}]},
        }
    )
    lines = [
        turn("m1", 10, 1000, 0, "prism task x"),
        result,
        turn("m1", 10, 1000, 0),
        turn("m2", 5, 0, 1000, at="2026-01-01T00:00:10Z"),
    ]
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    got = edit_bench.measure_transcript(path)
    assert got["turns"] == 2  # the repeated message id counts once
    assert got["total_input"] == 1010 + 1005
    assert got["billable"] == round(15 + 1000 * 1.25 + 1000 * 0.1)
    assert got["first_context"] == 1010 and got["work_context"] == -5
    assert got["prism_calls"] == 1 and got["tool_output"] == 100 and got["seconds"] == 10.0


def test_report_compares_arms_against_the_baseline(tmp_path: Path) -> None:
    def row(total: int) -> dict[str, float]:
        return {c: total for c in edit_bench._COLUMNS}

    (tmp_path / "measure.json").write_text(
        json.dumps({"t/without": row(1000), "t/tool": row(900), "t/hook": row(500)}),
        encoding="utf-8",
    )
    (tmp_path / "verify.json").write_text(
        json.dumps({f"t/{a}": {"passed": 3, "total": 3} for a in ("without", "tool", "hook")}),
        encoding="utf-8",
    )
    text = edit_bench.report(tmp_path)
    assert "| total_input | 1,000 | 900 (-10%) | 500 (-50%) |" in text
    assert "| checks passed | 3/3 | 3/3 | 3/3 |" in text


def test_prepare_refuses_to_overwrite(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(SystemExit):
        edit_bench.prepare(FIXTURE, TASKS, tmp_path)
    shutil.rmtree(tmp_path)
