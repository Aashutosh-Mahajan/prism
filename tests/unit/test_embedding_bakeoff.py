"""Audit committed embedding evidence without downloading models."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_embedding_denominators_and_sequential_runs():
    reports = [
        json.loads(
            (ROOT / "docs/benchmarks/embedding-2026-10-11" / (name + ".json")).read_text(
                encoding="utf-8"
            )
        )
        for name in ("minilm", "coderank")
    ]
    assert reports[0]["run_finished_unix"] < reports[1]["run_started_unix"]
    assert reports[0]["dataset_sha256"] == reports[1]["dataset_sha256"]
    for report in reports:
        assert len(report["rows"]) == 40
        assert sum(len(row["gold"]) for row in report["rows"]) == 61
        assert report["remote_code_trust"] is False
        assert report["api_spend"] == 0
        for prefix, rows in (("file", report["rows"]), ("code", report["code_rows"])):
            denominator = sum(len(row["gold"]) for row in rows)
            for k in (5, 10):
                hits = sum(len(set(row["gold"]) & set(row["top10"][:k])) for row in rows)
                assert report[f"{prefix}_recall{k}"] == hits / denominator
        for row in report["code_rows"]:
            assert row["exclude"] not in row["top10"]
        assert any(not set(row["gold"]) & set(row["top10"]) for row in report["rows"])
