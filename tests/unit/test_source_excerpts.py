from types import SimpleNamespace

from prism.navigator.task_pack import _Block, _delivered, _source_excerpt, _source_ranges
from tests.benchmarks.replay_precision import parse_packet


def test_secondary_matches_are_delivered_without_claiming_the_gap() -> None:
    block = _Block("module.py", 1, 100, None, 10, [40, 80], whole=True)
    ranges = _source_ranges(block, 1, 100, primary=False)
    assert ranges == [(1, 1), (37, 43), (77, 83)]
    source = _source_excerpt([f"statement {i}" for i in range(1, 101)], ranges)
    packet = f"candidate: module.py:1-100\n```\n{source}\n```"
    parsed = parse_packet(packet)[0]
    assert {1, 40, 80} <= parsed.delivered_lines
    assert 20 not in parsed.delivered_lines
    item = {
        "file": "module.py",
        "lines": [1, 100],
        "source": source,
        "source_ranges": [list(pair) for pair in ranges],
    }
    assert ("module.py", 37, 43) in _delivered({"blocks": [item]})
    assert ("module.py", 1, 100) not in _delivered({"blocks": [item]})


def test_primary_keeps_whole_body_and_named_constant_is_kept() -> None:
    primary = _Block("module.py", 1, 100, None, 10, [40], whole=True)
    assert _source_ranges(primary, 1, 100, primary=True) == [(1, 100)]
    constant = _Block("module.py", 120, 120, SimpleNamespace(start=120, end=120), 20, [120])
    assert _source_ranges(constant, 120, 120, primary=False) == [(120, 120)]
