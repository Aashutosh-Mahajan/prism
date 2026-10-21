"""The test-runner probe: withhold a Run line only when the runner provably cannot start."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.navigator import verify_env


@pytest.fixture(autouse=True)
def _cache_here(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("prism.consent.cache_root", lambda root: tmp_path / "cache")


def test_known_runners_and_unknown_commands() -> None:
    assert verify_env._needs("cd backend && python manage.py test") == ("python", "django")
    assert verify_env._needs("python -m pytest -q tests/test_a.py") == ("python", "pytest")
    assert verify_env._needs("cd web && npx vitest run a.test.ts") == ("node", "vitest")
    assert verify_env._needs("npm test") == ("node", "")
    assert verify_env._needs("go test ./...") == ("go", "go")
    assert verify_env._needs("make check") is None  # unknown: never claimed unrunnable


def test_missing_python_module_is_reported_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "backend").mkdir()
    calls = []

    def probe(directory: Path, kind: str, name: str) -> str:
        calls.append(name)
        return f"{name} is not installed for the python on PATH"

    monkeypatch.setattr(verify_env, "_probe", probe)
    command = "cd backend && python manage.py test"
    assert "django is not installed" in verify_env.unrunnable(tmp_path, command)
    assert "django is not installed" in verify_env.unrunnable(tmp_path, command)
    assert calls == ["django"]  # the second answer comes from the cache


def test_node_runner_needs_node_modules(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    assert verify_env.unrunnable(tmp_path, "cd web && npx jest a.test.ts") == (
        "node_modules is not installed"
    )
    (web / "node_modules" / ".bin").mkdir(parents=True)
    (web / "node_modules" / ".bin" / "jest").write_text("")
    assert verify_env.unrunnable(tmp_path, "cd web && npx jest b.test.ts") == ""


def test_a_python_module_that_exists_is_runnable(tmp_path: Path) -> None:
    # `json` is in every standard library, so the probe must find it and allow the command.
    assert verify_env._probe(tmp_path, "python", "json") == ""
