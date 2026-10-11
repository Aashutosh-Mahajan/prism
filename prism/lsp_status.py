"""Conservative language-server configuration hints; no LSP runtime dependency."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

_SERVERS = {
    "python": ("pyright", "pylsp", "basedpyright"),
    "typescript": ("typescript-language-server",),
    "javascript": ("typescript-language-server",),
    "go": ("gopls",),
    "rust": ("rust-analyzer",),
    "java": ("jdtls",),
    "dart": ("dart",),
    "kotlin": ("kotlin-language-server",),
    "swift": ("sourcekit-lsp",),
    "c": ("clangd",),
    "cpp": ("clangd",),
    "csharp": ("OmniSharp",),
}
_PLUGIN = {
    "python": ("pyright-lsp", "python-lsp", "basedpyright"),
    "typescript": ("typescript-lsp",),
    "javascript": ("typescript-lsp",),
    "go": ("gopls-lsp",),
    "rust": ("rust-analyzer-lsp",),
    "java": ("jdtls-lsp",),
    "dart": ("dart-lsp",),
    "kotlin": ("kotlin-lsp",),
    "swift": ("swift-lsp", "sourcekit-lsp"),
    "c": ("clangd-lsp",),
    "cpp": ("clangd-lsp",),
    "csharp": ("csharp-lsp",),
}


def language_server_status(root: Path, languages: dict[str, Any]) -> tuple[bool | None, str]:
    counts = {
        name: value
        for name, value in languages.items()
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    if not counts:
        return None, "no main indexed language; see docs/lsp-and-prism.md"
    language = min(counts, key=lambda name: (-counts[name], name))
    enabled: set[str] = set()
    for path in (
        Path.home() / ".claude/settings.json",
        root / ".claude/settings.json",
        root / ".claude/settings.local.json",
    ):
        try:
            if path.is_symlink() or path.stat().st_size > 1024 * 1024:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            plugins = data.get("enabledPlugins", {})
            if isinstance(plugins, dict):
                for name, value in plugins.items():
                    if value is True:
                        enabled.add(name)
                    elif value is False:
                        enabled.discard(name)
        except (OSError, ValueError, AttributeError):
            continue
    matches = sorted(name for name in enabled if name.split("@", 1)[0] in _PLUGIN.get(language, ()))
    installed = [name for name in _SERVERS.get(language, ()) if shutil.which(name)]
    if matches:
        return (
            True,
            f"{language}: enabled Claude plugin {', '.join(matches)}; runtime availability not probed",
        )
    suffix = "; executable on PATH: " + ", ".join(installed) if installed else ""
    return (
        None,
        f"{language}: no recognized language-server plugin configured{suffix}; see docs/lsp-and-prism.md",
    )
