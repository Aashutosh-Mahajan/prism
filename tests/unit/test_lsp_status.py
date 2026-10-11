import json
from pathlib import Path

from prism.lsp_status import language_server_status


def test_enabled_plugin_and_local_disable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("prism.lsp_status.shutil.which", lambda name: None)
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps({"enabledPlugins": {"pyright-lsp@claude-plugins-official": True}}),
        encoding="utf-8",
    )
    ok, detail = language_server_status(tmp_path, {"python": 8, "javascript": 1})
    assert ok is True and "enabled Claude plugin" in detail
    settings.with_name("settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"pyright-lsp@claude-plugins-official": False}}),
        encoding="utf-8",
    )
    ok, detail = language_server_status(tmp_path, {"python": 8})
    assert ok is None and "no recognized" in detail


def test_installed_binary_is_not_claimed_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        "prism.lsp_status.shutil.which", lambda name: "/bin/gopls" if name == "gopls" else None
    )
    ok, detail = language_server_status(tmp_path, {"go": 2})
    assert ok is None and "executable on PATH: gopls" in detail
    assert language_server_status(tmp_path, {})[0] is None
