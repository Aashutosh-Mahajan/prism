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


def test_saved_output_round_trip_queries_and_caps(tmp_path: Path) -> None:
    from prism.outputfilter import save_tee, show_tee

    text = "".join(f"progress {i}\n" for i in range(3000))
    text = text.replace("progress 1500\n", "ERROR: needle\n")
    saved = save_tee(tmp_path, "pytest", text)
    assert saved is not None
    assert saved.read_bytes() == text.encode("utf-8")
    assert show_tee(tmp_path, saved.stem, cap=64000) == text
    assert show_tee(tmp_path, saved.stem, grep="needle") == "1501: ERROR: needle\n"
    nearby = show_tee(tmp_path, saved.stem, around=1501, context=1)
    assert nearby == "1500: progress 1499\n1501: ERROR: needle\n1502: progress 1501\n"
    assert show_tee(tmp_path, saved.stem, tail=1) == "3000: progress 2999\n"
    capped = show_tee(tmp_path, saved.stem, cap=256)
    assert len(capped) <= 256 and "truncated" in capped and "--around" in capped


def test_saved_output_cli_preserves_crlf_bytes(tmp_path: Path) -> None:
    from prism.outputfilter import save_tee

    text = "first line\r\nERROR: second line\r\n"
    saved = save_tee(tmp_path, "pytest", text)
    assert saved is not None
    result = CliRunner().invoke(app, ["filter", "--root", str(tmp_path), "--show", saved.stem])
    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == text.encode("utf-8")


@pytest.mark.parametrize("identity", ["../secret", "000000-abcd1234/../x", "missing"])
def test_saved_output_rejects_paths(tmp_path: Path, identity: str) -> None:
    from prism.core.errors import UserError
    from prism.outputfilter import show_tee

    with pytest.raises(UserError, match="invalid"):
        show_tee(tmp_path, identity)


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


def test_save_failure_returns_all_bytes_and_failed_exit(
    tmp_path: Path, monkeypatch, capfdbinary
) -> None:
    from types import SimpleNamespace

    from prism import outputfilter

    raw = b"".join(f"progress {i}\r\n".encode() for i in range(300)) + b"ERROR: boom\r\n"
    monkeypatch.setattr(
        outputfilter.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=raw, stderr=b"stderr\r\n", returncode=3),
    )
    monkeypatch.setattr(outputfilter, "save_tee", lambda *args, **kwargs: None)
    assert outputfilter.run_filtered(tmp_path, ["some-tool"]) == 3
    assert capfdbinary.readouterr().out == raw + b"stderr\r\n"


def test_measured_savings_skip_invalid_metadata(tmp_path: Path) -> None:
    import json

    from prism.outputfilter import saved_saving, tee_dir

    assert saved_saving(tmp_path) is None
    directory = tee_dir(tmp_path)
    directory.mkdir(parents=True)
    for number, row in enumerate(
        [
            {"characters_in": 1000, "characters_out": 200},
            {"characters_in": True, "characters_out": 0},
            {"characters_in": 0, "characters_out": 0},
            {"characters_in": 4000, "characters_out": 400},
        ]
    ):
        (directory / f"120000-0000000{number}.meta.json").write_text(
            json.dumps(row), encoding="utf-8"
        )
    assert saved_saving(tmp_path) == (2, 88.0)
