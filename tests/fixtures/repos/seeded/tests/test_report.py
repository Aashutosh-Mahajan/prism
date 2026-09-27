from ledger.report import total


def test_total() -> None:
    assert total([1.0, 2.5]) == 350
