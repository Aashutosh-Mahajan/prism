"""Retrieval quality is a tested property: the core cases must be located in one call."""

from __future__ import annotations

import pytest

from tests.benchmarks import retrieval_eval

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")


@pytest.fixture(scope="module")
def rows() -> list[dict[str, object]]:
    return retrieval_eval.evaluate("all")


def test_every_core_case_is_located_in_one_call(rows: list[dict[str, object]]) -> None:
    missed = [(r["query"], r["missing"]) for r in rows if r["tier"] == "core" and not r["located"]]
    assert not missed, missed


def test_exact_evidence_cases_are_always_located(rows: list[dict[str, object]]) -> None:
    exact = [r for r in rows if r["kind"] in ("quantity", "identifier", "quoted", "structural")]
    assert exact and all(r["located"] for r in exact)


def test_answers_stay_small(rows: list[dict[str, object]]) -> None:
    summary = retrieval_eval.summarise(rows)  # type: ignore[arg-type]
    assert summary["all"]["tokens"] < 1300
    assert max(int(str(r["tokens"])) for r in rows) <= 2000


def test_stretch_cases_are_reported_but_not_required(rows: list[dict[str, object]]) -> None:
    stretch = [r for r in rows if r["tier"] == "stretch"]
    assert stretch  # the hard cases stay visible so progress on them can be seen


def test_the_scorer_counts_literals_blocks_and_call_sites() -> None:
    pack = {
        "literals": [{"occurrences": [{"file": "a.py", "line": 3}]}],
        "blocks": [
            {"file": "b.py", "lines": [10, 20], "source": "x"},
            {"file": "c.py", "lines": [1, 5], "seen": True},
        ],
        "links": [{"role": "caller", "file": "d.py", "line": 7}],
    }
    assert retrieval_eval.covered(pack, "a.py", 3)
    assert retrieval_eval.covered(pack, "b.py", 15) and not retrieval_eval.covered(pack, "b.py", 21)
    assert not retrieval_eval.covered(pack, "c.py", 2)  # a reference carries no code
    assert retrieval_eval.covered(pack, "d.py", 7)
    assert not retrieval_eval.covered(pack, "a.py", 4)
