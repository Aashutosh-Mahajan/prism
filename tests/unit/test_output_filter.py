"""`prism filter`: shorter output, never without the failures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.lifecycle import apply_init, plan_init, scan
from prism.outputfilter import FAILURE, filter_output

PYTEST_OUTPUT = (
    ["============================= test session starts ==============================="]
    + ["platform win32 -- Python 3.14", "rootdir: /x", "collected 120 items", ""]
    + [
        f"tests/test_mod{i}.py ....................                              [{i}%]"
        for i in range(90)
    ]
    + ["=================================== FAILURES ==================================="]
    + ["_______________________________ test_discount ________________________________"]
    + ["    def test_discount():", ">       assert apply(10) == 9", "E       assert 10 == 9"]
    + ["tests/test_discount.py:12: AssertionError"]
    + ["=========================== short test summary info ============================"]
    + ["FAILED tests/test_discount.py::test_discount - assert 10 == 9"]
    + ["========================= 1 failed, 119 passed in 3.21s ========================"]
)


def test_short_output_is_unchanged() -> None:
    text = "ok\n" * 10
    assert filter_output("pytest -q", text).text == text


def test_pytest_keeps_every_failure_and_the_result_line_and_drops_progress() -> None:
    result = filter_output("python -m pytest -q", "\n".join(PYTEST_OUTPUT))
    assert result.lines_out < result.lines_in // 2
    for needed in (
        "FAILED tests/test_discount.py::test_discount - assert 10 == 9",
        "E       assert 10 == 9",
        ">       assert apply(10) == 9",
        "tests/test_discount.py:12: AssertionError",
        "1 failed, 119 passed",
    ):
        assert needed in result.text
    assert "tests/test_mod7.py ...." not in result.text


@pytest.mark.parametrize(
    "command,lines",
    [
        (
            "go test ./...",
            ["--- PASS: TestA (0.00s)"] * 80
            + ["--- FAIL: TestB (0.01s)", "    b_test.go:9: got 1, want 2"],
        ),
        (
            "cargo test",
            ["test a::b ... ok"] * 80
            + ["test c::d ... FAILED", "thread 'c::d' panicked at src/lib.rs:4"],
        ),
        (
            "npm test",
            ["PASS src/a.test.js"] * 80 + ["FAIL src/b.test.js", "  ● b › adds", "    Expected: 3"],
        ),
        (
            "flutter test",
            [f"00:{i % 60:02d} +{i}: loading test/a_test.dart" for i in range(80)]
            + ["00:59 +80 -1: test/a_test.dart: adds [E]", "  Expected: <3>"],
        ),
        (
            "some-tool --all",
            [f"processing item {i}" for i in range(300)] + ["fatal: could not open file"],
        ),
    ],
)
def test_every_family_keeps_its_failure_lines(command: str, lines: list[str]) -> None:
    failing = [line for line in lines if FAILURE.search(line)]
    assert failing
    result = filter_output(command, "\n".join(lines))
    assert result.lines_out < result.lines_in
    for line in failing:
        assert line in result.text


def test_a_long_git_diff_is_not_cut_in_the_middle() -> None:
    diff = "\n".join(f"+line {i}" for i in range(400))
    assert filter_output("git diff", diff).text.count("+line") == 400


def test_the_command_prints_the_tee_path_and_keeps_the_exit_status(tmp_path: Path) -> None:
    from tests.conftest import copy_fixture  # type: ignore[import-not-found]

    repo = copy_fixture("small", tmp_path)
    apply_init(plan_init(repo))
    scan(repo)
    script = repo / "noisy.py"
    script.write_text(
        "import sys\nfor i in range(300):\n    print('progress', i)\nprint('ERROR: boom')\nsys.exit(3)\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["filter", "--root", str(repo), "--", sys.executable, str(script)]
    )
    assert result.exit_code == 3
    assert "ERROR: boom" in result.output and "full output:" in result.output
    assert result.output.count("progress") < 80
    tee = next((repo / ".aicontext" / "cache" / "tee").glob("*.txt"))
    assert tee.read_text(encoding="utf-8").count("progress") == 300
