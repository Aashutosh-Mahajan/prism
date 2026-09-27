from __future__ import annotations

from pathlib import Path

from prism.config import PrismConfig
from prism.discovery import detect_language, discover


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _paths(root: Path, config: PrismConfig | None = None) -> list[str]:
    return [f.path for f in discover(root, config or PrismConfig())]


def test_detect_language_by_extension_and_shebang() -> None:
    assert detect_language("a/b.py") == "python"
    assert detect_language("a/b.TSX") == "typescript"
    assert detect_language("README.md") is None
    assert detect_language("bin/run", "#!/usr/bin/env python3") == "python"
    assert detect_language("bin/run", "#!/bin/bash") == "shell"
    assert detect_language("bin/run", "hello") is None
    assert detect_language("dir.v2/run") is None


def test_builtin_ignores(tmp_path: Path) -> None:
    _write(tmp_path, "app.py")
    _write(tmp_path, "node_modules/lib/index.js")
    _write(tmp_path, ".venv/lib/x.py")
    _write(tmp_path, "__pycache__/app.py")
    _write(tmp_path, "pkg.egg-info/x.py")
    _write(tmp_path, "myenv/pyvenv.cfg", "home = /usr\n")
    _write(tmp_path, "myenv/lib/site.py")
    assert _paths(tmp_path) == ["app.py"]


def test_gitignore_is_scoped_to_its_directory(tmp_path: Path) -> None:
    _write(tmp_path, ".gitignore", "*.gen.py\n/top_only.py\n")
    _write(tmp_path, "sub/.gitignore", "local.py\n!keep.gen.py\n")
    for rel in [
        "a.py",
        "a.gen.py",
        "top_only.py",
        "sub/top_only.py",
        "sub/local.py",
        "local.py",
        "sub/keep.gen.py",
        "sub/x.gen.py",
    ]:
        _write(tmp_path, rel)
    assert _paths(tmp_path) == ["a.py", "local.py", "sub/keep.gen.py", "sub/top_only.py"]


def test_prismignore_and_config_ignore(tmp_path: Path) -> None:
    _write(tmp_path, ".prismignore", "legacy/\n")
    for rel in ["a.py", "legacy/old.py", "vendorized/x.py"]:
        _write(tmp_path, rel)
    assert _paths(tmp_path, PrismConfig(ignore=("vendorized/",))) == ["a.py"]


def test_size_limit_binary_and_unknown_files(tmp_path: Path) -> None:
    _write(tmp_path, "ok.py")
    _write(tmp_path, "big.py", "x = 1\n" * 100)
    (tmp_path / "bin.py").write_bytes(b"\x00\x01binary")
    _write(tmp_path, "notes.txt", "hello")
    _write(tmp_path, "script", "#!/usr/bin/env python\nprint(1)\n")
    assert _paths(tmp_path, PrismConfig(max_file_size=100)) == ["ok.py", "script"]


def test_output_is_sorted_with_hashes(tmp_path: Path) -> None:
    for rel in ["z.py", "a/b.py", "a.py"]:
        _write(tmp_path, rel)
    files = discover(tmp_path, PrismConfig())
    assert [f.path for f in files] == ["a.py", "a/b.py", "z.py"]
    assert all(len(f.sha256) == 64 for f in files)


def test_known_hashes_are_reused_for_unchanged_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.py")
    first = discover(tmp_path, PrismConfig())[0]
    known = {
        "a.py": {"sha256": "f" * 64, "mtime": first.mtime, "size": first.size, "language": "python"}
    }
    assert discover(tmp_path, PrismConfig(), known)[0].sha256 == "f" * 64


def test_minified_and_generated_bundles_are_skipped(tmp_path: Path) -> None:
    bundle = "var a=function(b){return b+1};" * 700  # one very long ~22 KB line
    _write(tmp_path, "dist2/app.js", bundle)
    _write(tmp_path, "static/lib.min.js", "function f() {}\n")
    _write(tmp_path, "static/app.js.map", "{}\n")
    _write(tmp_path, "src/app.js", "function f(x) {\n  return x + 1;\n}\n" * 200)
    assert _paths(tmp_path) == ["src/app.js"]
    # A bundle indexed by an older version drops out even on the unchanged-file fast path.
    stat = (tmp_path / "dist2/app.js").stat()
    known = {
        "dist2/app.js": {
            "sha256": "f" * 64,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "language": "javascript",
        }
    }
    assert [f.path for f in discover(tmp_path, PrismConfig(), known)] == ["src/app.js"]


def test_network_guard_blocks_external_hosts() -> None:
    import socket

    import pytest

    from tests.conftest import NetworkBlocked

    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
