"""The findings store `.aicontext/audit/findings.json` and audit paths.

All writes go through `write_findings` (a writers helper), keeping the
"only writers write .aicontext" rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prism import SCHEMA_VERSION
from prism.core.paths import AICONTEXT
from prism.writers.json_writer import write_json


def audit_dir(root: Path) -> Path:
    return root / AICONTEXT / "audit"


def findings_path(root: Path) -> Path:
    return audit_dir(root) / "findings.json"


def plan_path(root: Path) -> Path:
    return audit_dir(root) / "audit_plan.json"


def load_findings(root: Path) -> dict[str, Any]:
    path = findings_path(root)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("findings", [])
                return data
        except ValueError:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "current_audit": None,
        "last_report": None,
        "findings": [],
    }


def write_findings(root: Path, data: dict[str, Any]) -> None:
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    data["findings"] = sorted(
        data.get("findings", []), key=lambda f: int(str(f["id"]).split("-")[1])
    )
    write_json(findings_path(root), data)
