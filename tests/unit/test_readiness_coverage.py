from prism.navigator.literals import EvidenceResult
from prism.navigator.task_pack import _confidence


def test_unindexed_request_words_cannot_inflate_confidence() -> None:
    pack = {
        "blocks": [
            {
                "source": "def total(amount): return amount",
                "symbol": "total",
                "role": "match",
                "truncated": False,
            }
        ],
        "stale_sources": 0,
    }
    _confidence(
        pack,
        EvidenceResult(),
        [],
        {"amount": 1.0},
        False,
        "convert a dollar amount to whole integer pennies",
    )
    assert pack["confidence"] == "medium"
    assert not pack["sufficient"]
