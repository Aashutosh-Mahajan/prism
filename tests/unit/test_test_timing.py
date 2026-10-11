from pathlib import Path

from prism.navigator.test_timing import record_full_suite, slow_suite_warning


def test_observed_full_suite_and_selected_tests(tmp_path: Path) -> None:
    assert slow_suite_warning(tmp_path) is None
    record_full_suite(tmp_path, "pytest tests/unit -q", 240)
    assert slow_suite_warning(tmp_path) is None
    record_full_suite(tmp_path, "python -m pytest -q", 119)
    assert slow_suite_warning(tmp_path) is None
    record_full_suite(tmp_path, "python -m pytest -q", 241)
    assert slow_suite_warning(tmp_path) == "full suite takes ~4 min; run the named tests only"


def test_explicit_setting_does_not_invent_duration(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.prism]\nslow_tests = true\n", encoding="utf-8")
    assert slow_suite_warning(tmp_path) == "full suite is marked slow; run the named tests only"
