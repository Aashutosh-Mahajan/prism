from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from prism.audit import build_plan, build_report, detect_toolchain, record_finding, update_status
from prism.core.errors import NotFoundError, UserError
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator import api
from prism.navigator.store import IndexStore
from prism.status import compute_status

FIXTURES = Path(__file__).parents[1] / "fixtures" / "repos"
SCHEMAS = Path(__file__).parents[2] / "prism" / "schemas"


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    repo = shutil.copytree(FIXTURES / "seeded", tmp_path / "seeded")
    apply_init(plan_init(repo))
    scan(repo)
    return repo


def finding(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Coupon applied to the original price instead of the sale price",
        "severity": "high",
        "category": "correctness",
        "confidence": "confirmed",
        "file": "ledger/pricing.py",
        "lines": [8, 12],
        "symbol": "ledger.pricing.apply_discount",
        "description": "apply_discount multiplies the coupon by the original price, so discounts stack wrongly.",
        "evidence": {
            "type": "failing_test",
            "command": "pytest tests/test_pricing.py -q",
            "output_excerpt": "assert 80.0 == 81.0",
        },
        "suggested_fix": "Compute the coupon saving from the sale price.",
    }
    base.update(overrides)
    return base


def test_toolchain_detection(seeded: Path, tmp_path: Path) -> None:
    assert detect_toolchain(seeded) == [
        {"kind": "test", "command": "python -m pytest -q", "detected_from": "pytest configuration"}
    ]
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\n[project.optional-dependencies]\ndev=["pytest","pytest-cov"]\n'
        "[tool.mypy]\nstrict=true\n[tool.ruff]\n"
    )
    kinds = [t["kind"] for t in detect_toolchain(tmp_path)]
    assert kinds == ["test", "typecheck", "lint", "coverage"]


def test_plan_ranks_seeded_bugs(seeded: Path) -> None:
    bugs = json.loads((seeded / "SEEDED_BUGS.json").read_text())["bugs"]
    quick = build_plan(seeded, depth="quick")
    top_files = {t["file"] for t in quick["targets"]}
    hits = [b for b in bugs if b["file"] in top_files]
    assert len(hits) >= 6, f"only {len(hits)} of {len(bugs)} seeded files in the quick top 10"

    plan = build_plan(seeded, depth="standard")
    jsonschema.validate(plan, json.loads((SCHEMAS / "audit_plan.schema.json").read_text()))
    covered = (
        {t["file"] for t in plan["targets"]}
        | {s["file"] for s in plan["smells"]}
        | {d["file"] for d in plan["dead_code"]}
    )
    assert all(b["file"] in covered for b in bugs if b["file"] != "ledger/report.py")
    smell_kinds = {s["kind"] for s in plan["smells"]}
    assert {
        "sql_string_formatting",
        "dangerous_call",
        "hardcoded_secret",
        "mutable_default",
        "bare_except",
        "missing_await",
    } <= smell_kinds
    assert "ledger.legacy_export._old_format" in {d["id"] for d in plan["dead_code"]}
    assert plan["toolchain"][0]["kind"] == "test"
    assert all(t["context"].startswith("prism context ") for t in plan["targets"])


def test_plan_scopes(seeded: Path) -> None:
    only = build_plan(seeded, scope="ledger/storage.py")
    assert {t["file"] for t in only["targets"]} == {"ledger/storage.py"}
    with pytest.raises(UserError):
        build_plan(seeded, scope="nope/")
    with pytest.raises(UserError):
        build_plan(seeded, depth="extreme")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_plan_changed_scope(seeded: Path) -> None:
    _git(seeded, "init", "-q")
    _git(seeded, "add", ".")
    _git(seeded, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=seeded, capture_output=True, text=True
    ).stdout.strip()
    (seeded / "ledger" / "utils.py").write_text(
        (seeded / "ledger" / "utils.py").read_text()
        + "\n\ndef dollars(c: int) -> float:\n    return c / 100\n"
    )
    scan(seeded)
    plan = build_plan(seeded, scope="changed", since=base)
    assert plan["scope"]["files"] and "ledger/utils.py" in plan["scope"]["files"]
    assert {t["file"] for t in plan["targets"]} == {"ledger/utils.py"}


def test_record_validates(seeded: Path) -> None:
    build_plan(seeded)
    with pytest.raises(UserError, match="severity"):
        record_finding(seeded, finding(severity="urgent"))
    with pytest.raises(UserError, match="confirmed"):
        record_finding(seeded, finding(confidence="likely"))
    ok = record_finding(seeded, finding(confidence="likely", reason="needs a live bank feed"))
    assert ok == {"id": "F-001", "result": "created"}
    with pytest.raises(UserError, match="does not exist"):
        record_finding(
            seeded, finding(file="ledger/nope.py", title="Another distinct problem here")
        )
    with pytest.raises(UserError, match="only"):
        record_finding(seeded, finding(lines=[1, 999], title="Line range beyond the end of file"))


def test_record_dedupes_and_reopens(seeded: Path) -> None:
    build_plan(seeded)
    assert record_finding(seeded, finding())["id"] == "F-001"
    dup = record_finding(
        seeded, finding(title="Coupon is applied to original price, not sale price")
    )
    assert dup == {"id": "F-001", "result": "duplicate_updated"}
    other = record_finding(
        seeded,
        finding(
            title="SQL query built with an f-string",
            category="security",
            file="ledger/storage.py",
            lines=[10, 14],
            symbol="ledger.storage.find_entries",
            severity="critical",
        ),
    )
    assert other["id"] == "F-002"
    update_status(seeded, "F-001", "fixed")
    reopened = record_finding(seeded, finding())
    assert reopened == {"id": "F-001", "result": "reopened"}
    data = json.loads((seeded / ".aicontext" / "audit" / "findings.json").read_text())
    jsonschema.validate(data, json.loads((SCHEMAS / "findings.schema.json").read_text()))
    history = data["findings"][0]["history"]
    assert [h["status"] for h in history] == ["fixed", "open"]
    with pytest.raises(NotFoundError):
        update_status(seeded, "F-999", "fixed")
    with pytest.raises(UserError):
        update_status(seeded, "F-001", "done")


def test_report_diffs_across_audits(seeded: Path) -> None:
    build_plan(seeded)
    record_finding(seeded, finding())
    record_finding(
        seeded,
        finding(
            title="Mutable default argument accumulates tags",
            category="correctness",
            file="ledger/utils.py",
            lines=[4, 7],
            symbol="ledger.utils.tag",
            severity="medium",
        ),
    )
    first = build_report(seeded)
    assert first["new"] == ["F-001", "F-002"] and first["fixed"] == [] and first["persisting"] == []
    report = (seeded / ".aicontext" / "audit" / "REPORT.md").read_text()
    assert (
        "# PRISM Audit Report" in report and "F-001" in report and "assert 80.0 == 81.0" in report
    )

    build_plan(seeded)  # second audit
    update_status(seeded, "F-001", "fixed")
    record_finding(
        seeded,
        finding(
            title="Coroutine flush() is never awaited",
            category="concurrency",
            file="ledger/worker.py",
            lines=[11, 14],
            symbol="ledger.worker.run_once",
            severity="medium",
            confidence="likely",
        ),
    )
    second = build_report(seeded)
    assert second["new"] == ["F-003"]
    assert second["fixed"] == ["F-001"]
    assert second["persisting"] == ["F-002"]
    history = list((seeded / ".aicontext" / "audit" / "history").glob("REPORT-*.md"))
    assert len(history) == 2


def test_findings_flow_into_navigation_and_status(seeded: Path) -> None:
    build_plan(seeded)
    record_finding(seeded, finding())
    store = IndexStore.open(seeded)
    pack = api.op_context(store, "ledger.pricing.apply_discount")
    assert pack["open_findings"] == ["F-001"]
    store.close()
    status = compute_status(seeded)
    assert status.audit is not None and status.audit["open"] == 1
    assert "1 open audit findings" in api.op_brief(seeded)["freshness"]
    scan(seeded)  # risk incorporates open findings at the next scan
    health = json.loads((seeded / ".aicontext" / "health.json").read_text())
    assert "1 open audit finding" in health["files"]["ledger/pricing.py"]["reasons"]
    plan = build_plan(seeded)
    assert plan["reverify"][0]["id"] == "F-001"
    assert plan["reverify"][0]["evidence_command"] == "pytest tests/test_pricing.py -q"
