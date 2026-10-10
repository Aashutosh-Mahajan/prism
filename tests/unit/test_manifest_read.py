"""A manifest read that races the writer's atomic replace is retried, not failed."""

from __future__ import annotations

from pathlib import Path

import pytest

from prism.writers import manifest as manifest_module
from prism.writers.manifest import load_manifest


def test_a_transient_permission_error_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".aicontext").mkdir()
    (tmp_path / ".aicontext" / "manifest.json").write_text('{"files": {}}', encoding="utf-8")
    real = manifest_module.read_json
    calls = {"n": 0}

    def flaky(path: Path) -> object:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("replaced")
        return real(path)

    monkeypatch.setattr(manifest_module, "read_json", flaky)
    monkeypatch.setattr(manifest_module, "READ_PAUSE", 0)
    assert load_manifest(tmp_path) == {"files": {}}
    assert calls["n"] == 3


def test_a_permanent_permission_error_still_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".aicontext").mkdir()
    (tmp_path / ".aicontext" / "manifest.json").write_text("{}", encoding="utf-8")

    def denied(path: Path) -> object:
        raise PermissionError("no")

    monkeypatch.setattr(manifest_module, "read_json", denied)
    monkeypatch.setattr(manifest_module, "READ_PAUSE", 0)
    with pytest.raises(PermissionError):
        load_manifest(tmp_path)
