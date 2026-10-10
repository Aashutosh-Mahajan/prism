from types import SimpleNamespace

from prism.navigator.task_pack import _Block, _knapsack_blocks, _select


def test_knapsack_maximizes_total_score_instead_of_greedy_biggest() -> None:
    pack = {
        "intent": "edit",
        "confidence": "high",
        "stale_sources": 0,
        "blocks": [],
        "next": "",
        "budget": {"requested": 200, "used_est": 0},
    }
    lines = {"big.py": ["x" * 330], "a.py": ["x" * 120], "b.py": ["x" * 120]}
    blocks = [
        _Block("big.py", 1, 1, None, 12, [1]),
        _Block("a.py", 1, 1, None, 7, [1]),
        _Block("b.py", 1, 1, None, 7, [1]),
    ]
    selected = _knapsack_blocks(pack, blocks, SimpleNamespace(lines=lines.get), 200)
    assert [block.file for block in selected] == ["a.py", "b.py"]
    assert selected == _knapsack_blocks(pack, blocks, SimpleNamespace(lines=lines.get), 200)


def test_tight_floor_and_three_block_cap() -> None:
    blocks = [
        _Block(f"m{i}.py", 1, 1, None, score, [1]) for i, score in enumerate([100, 90, 80, 70, 49])
    ]
    assert len(_select(blocks, tight=True)) == 3


def test_already_delivered_primary_does_not_win_again() -> None:
    pack = {
        "intent": "edit",
        "confidence": "high",
        "stale_sources": 0,
        "blocks": [
            {
                "role": "candidate",
                "file": "a.py",
                "lines": [1, 1],
                "symbol": None,
                "truncated": False,
                "source": "1: value",
            }
        ],
        "next": "",
        "budget": {"requested": 500, "used_est": 0},
    }
    blocks = [_Block("a.py", 1, 1, None, 100, [1]), _Block("b.py", 1, 1, None, 10, [1])]
    selected = _knapsack_blocks(pack, blocks, SimpleNamespace(lines=lambda file: ["value"]), 500)
    assert [block.file for block in selected] == ["b.py"]
