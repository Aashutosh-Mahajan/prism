import json
from pathlib import Path

import pytest

from prism.writers import json_writer


def test_json_reader_recovers_from_transient_sharing_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "data.json"
    path.write_text('{"value": 1}')
    original = Path.read_text
    attempts = 0

    def read(self: Path, **kwargs: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated Windows sharing violation")
        return original(self, encoding="utf-8")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(json_writer.time, "sleep", lambda seconds: None)
    assert json_writer.read_json(path) == {"value": 1}
    assert attempts == 3


def test_permanent_denial_remains_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def denied(self: Path, **kwargs: object) -> str:
        nonlocal attempts
        attempts += 1
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", denied)
    monkeypatch.setattr(json_writer, "REPLACE_ATTEMPTS", 3)
    monkeypatch.setattr(json_writer.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        json_writer.read_json(tmp_path / "data.json")
    assert attempts == 3


def test_corrupt_json_is_not_hidden_by_retries(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text("bad json")
    with pytest.raises(json.JSONDecodeError):
        json_writer.read_json(path)
