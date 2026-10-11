from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.benchmarks.context_score import check_regression, score_context


def test_files_blocks_lines_and_observed_usage() -> None:
    packet = "match: a.py:1-5\n```\n1: one\ntwo\n⋮ 2 lines omitted\n5: five\n```\nmatch: noise.py:1\n```\n1: other\n```"
    result = score_context(
        packet, ["a.py", "new.py"], [("a.py", 2, 3), ("a.py", 5, 5)], [("a.py", 2, 2)]
    )
    assert result["file"]["precision"] == result["file"]["recall"] == 0.5
    assert result["block"]["precision"] == 0.5
    assert result["block"]["recall"] == 1.0
    assert result["line"]["precision"] == 0.5
    assert result["line"]["recall"] == pytest.approx(2 / 3)
    assert result["context_used_share"] == 0.25
    assert score_context(packet, ["a.py"], [])["context_used_share"] is None


def test_regression_uses_agreed_file_recall_margin() -> None:
    baseline = {"summary": {"file": {"recall": 0.2}}}
    check_regression({"summary": {"file": {"recall": 0.181}}}, baseline)
    with pytest.raises(AssertionError, match="two-point"):
        check_regression({"summary": {"file": {"recall": 0.179}}}, baseline)


@pytest.mark.context_regression
def test_frozen_context_regression() -> None:
    current = os.environ.get("PRISM_CONTEXT_SCORE")
    baseline = os.environ.get("PRISM_CONTEXT_BASELINE")
    if not current or not baseline:
        pytest.skip("set PRISM_CONTEXT_SCORE and PRISM_CONTEXT_BASELINE to frozen score reports")
    check_regression(
        json.loads(Path(current).read_text(encoding="utf-8")),
        json.loads(Path(baseline).read_text(encoding="utf-8")),
    )
