"""`prism audit record` / `prism audit update`: validated, deduplicated findings.

- IDs are stable `F-###`, never reused.
- Dedup key: (file, symbol, category) plus title similarity, or an identical
  fingerprint. A duplicate updates the existing finding instead of adding one;
  a previously fixed finding that is reported again is reopened (regression).
- `critical`/`high` require `confirmed` confidence or an explicit `reason`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from prism.audit.store import load_findings, write_findings
from prism.core.errors import NotFoundError, UserError
from prism.writers.manifest import now_iso

SEVERITIES = ("critical", "high", "medium", "low", "info")
CATEGORIES = (
    "correctness",
    "security",
    "error_handling",
    "concurrency",
    "resource",
    "performance",
    "api_contract",
    "test_gap",
    "dead_code",
    "maintainability",
    "config",
)
CONFIDENCES = ("confirmed", "likely", "suspected")
STATUSES = ("open", "fixed", "wontfix", "false_positive")
EVIDENCE_TYPES = ("failing_test", "repro_script", "tool_output", "code_reasoning")
TITLE_SIMILARITY = 0.5

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "finding_input.schema.json"


def _schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return data


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def fingerprint(finding: dict[str, Any]) -> str:
    key = "|".join(
        [
            finding["file"],
            finding.get("symbol") or "",
            finding["category"],
            " ".join(sorted(_words(finding["title"]))),
        ]
    )
    return "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def _similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    return len(wa & wb) / len(wa | wb) >= TITLE_SIMILARITY


def validate(finding: dict[str, Any], root: Path) -> list[str]:
    problems = [
        f"{'/'.join(str(p) for p in e.absolute_path) or 'finding'}: {e.message}"
        for e in sorted(jsonschema.Draft202012Validator(_schema()).iter_errors(finding), key=str)
    ]
    if problems:
        return problems
    needs_reason = (
        finding["severity"] in ("critical", "high") and finding["confidence"] != "confirmed"
    )
    if needs_reason and not str(finding.get("reason", "")).strip():
        problems.append(
            f"{finding['severity']} findings must be `confirmed`, or include a `reason` explaining why a repro was not possible"
        )
    start, end = finding["lines"]
    if start > end:
        problems.append("lines: start must be <= end")
    path = root / finding["file"]
    if not path.is_file():
        problems.append(
            f"file: '{finding['file']}' does not exist (use a path relative to the repo root)"
        )
    else:
        try:
            n = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            if end > max(n, 1):
                problems.append(f"lines: {finding['file']} has only {n} lines")
        except OSError:
            pass
    return problems


def record_finding(root: Path, finding: dict[str, Any]) -> dict[str, Any]:
    problems = validate(finding, root)
    if problems:
        raise UserError("finding rejected: " + "; ".join(problems), problems=problems)
    data = load_findings(root)
    audit = data.get("current_audit") or {}
    audit_id = audit.get("id") or now_iso()
    fp = fingerprint(finding)
    fields = {
        k: finding[k] for k in finding if k not in ("id", "status", "found_in_audit", "fingerprint")
    }

    for existing in data["findings"]:
        same_place = (
            existing["file"] == finding["file"]
            and existing.get("symbol") == finding.get("symbol")
            and existing["category"] == finding["category"]
        )
        if existing.get("fingerprint") == fp or (
            same_place and _similar(existing["title"], finding["title"])
        ):
            regressed = existing["status"] in ("fixed",)
            existing.update(fields)
            existing["fingerprint"] = fp
            existing["last_seen_in_audit"] = audit_id
            if regressed:
                existing["status"] = "open"
                existing.setdefault("history", []).append(
                    {"status": "open", "at": now_iso(), "note": "regressed"}
                )
            write_findings(root, data)
            return {
                "id": existing["id"],
                "result": "reopened" if regressed else "duplicate_updated",
            }

    next_num = max((int(str(f["id"]).split("-")[1]) for f in data["findings"]), default=0) + 1
    new = {
        **fields,
        "id": f"F-{next_num:03d}",
        "status": "open",
        "found_in_audit": audit_id,
        "last_seen_in_audit": audit_id,
        "fingerprint": fp,
    }
    new.setdefault("symbol", None)
    data["findings"].append(new)
    write_findings(root, data)
    return {"id": new["id"], "result": "created"}


def update_status(
    root: Path, finding_id: str, status: str, note: str | None = None
) -> dict[str, Any]:
    if status not in STATUSES:
        raise UserError(f"status must be one of {', '.join(STATUSES)}")
    data = load_findings(root)
    for f in data["findings"]:
        if f["id"] == finding_id:
            if f["status"] != status:
                entry: dict[str, Any] = {"status": status, "at": now_iso()}
                if note:
                    entry["note"] = note
                f.setdefault("history", []).append(entry)
                f["status"] = status
                audit = data.get("current_audit") or {}
                if status == "fixed" and audit.get("id"):
                    f["fixed_in_audit"] = audit["id"]
            write_findings(root, data)
            return dict(f)
    raise NotFoundError(
        f"no finding with id '{finding_id}'", suggestions=[f["id"] for f in data["findings"]][-10:]
    )
