from __future__ import annotations

import io
import zipfile
from pathlib import Path

from prism.launcher_status import launcher_status


def _windows_launcher(path: Path, module: str) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "__main__.py", f"import sys\nfrom {module} import main\nsys.exit(main())\n"
        )
    path.write_bytes(b"MZ" + b"\x00" * 64 + buffer.getvalue())
    return str(path)


def test_a_launcher_on_the_fast_entry_point_is_fine(tmp_path: Path) -> None:
    ok, detail = launcher_status(_windows_launcher(tmp_path / "prism.exe", "prism.entry"))
    assert ok is True and "fast" in detail


def test_a_launcher_generated_for_the_old_entry_point_is_flagged(tmp_path: Path) -> None:
    ok, detail = launcher_status(_windows_launcher(tmp_path / "prism.exe", "prism.cli"))
    assert ok is False and "reinstall" in detail


def test_a_script_launcher_and_missing_files_are_judged(tmp_path: Path) -> None:
    script = tmp_path / "prism"
    script.write_text("#!/usr/bin/python\nfrom prism.entry import main\nmain()\n", encoding="utf-8")
    assert launcher_status(str(script))[0] is True
    script.write_text("#!/usr/bin/python\nfrom prism.cli import main\nmain()\n", encoding="utf-8")
    assert launcher_status(str(script))[0] is False
    assert launcher_status(str(tmp_path / "absent"))[0] is None
