"""`prism audit report`: render `audit/REPORT.md`, diff against the last audit, archive.

Diff categories:
- new: open findings first found in the current audit
- fixed: findings marked fixed since the previous report
- persisting: open findings that were already open at the previous report
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from prism.audit.store import audit_dir, load_findings, write_findings
from prism.writers.json_writer import write_json, write_text
from prism.writers.manifest import now_iso

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _safe_stamp(stamp: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", stamp)


def _previous_snapshot(root: Path) -> dict[str, Any] | None:
    history = audit_dir(root) / "history"
    snaps = sorted(history.glob("findings-*.json")) if history.is_dir() else []
    if not snaps:
        return None
    data: dict[str, Any] = json.loads(snaps[-1].read_text(encoding="utf-8"))
    return data


def _row(f: dict[str, Any]) -> str:
    loc = f"{f['file']}:{f['lines'][0]}" + (
        f"-{f['lines'][1]}" if f["lines"][1] != f["lines"][0] else ""
    )
    return f"| {f['id']} | {f['severity']} | {f['category']} | {f['confidence']} | {f['title']} | `{loc}` |"


def _detail(f: dict[str, Any]) -> list[str]:
    ev = f.get("evidence") or {}
    lines = [
        f"### {f['id']} · {f['severity']} · {f['title']}",
        "",
        f"- **Where:** `{f['file']}` lines {f['lines'][0]}-{f['lines'][1]}"
        + (f" (`{f['symbol']}`)" if f.get("symbol") else ""),
        f"- **Category / confidence:** {f['category']} / {f['confidence']}",
        f"- **Status:** {f['status']}",
        "",
        f["description"],
        "",
        f"**Evidence ({ev.get('type', 'n/a')}):**"
        + (f" `{ev['command']}`" if ev.get("command") else ""),
    ]
    if ev.get("output_excerpt"):
        lines += ["", "```", str(ev["output_excerpt"]).strip(), "```"]
    if f.get("reason"):
        lines += ["", f"**Why not confirmed:** {f['reason']}"]
    lines += ["", f"**Suggested fix:** {f['suggested_fix']}", ""]
    return lines


def build_report(root: Path) -> dict[str, Any]:
    data = load_findings(root)
    findings: list[dict[str, Any]] = data["findings"]
    audit = data.get("current_audit") or {}
    audit_id = audit.get("id") or now_iso()
    previous = _previous_snapshot(root)
    prev_open = {f["id"] for f in (previous or {}).get("findings", []) if f.get("status") == "open"}

    open_items = sorted(
        (f for f in findings if f["status"] == "open"),
        key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["id"]),
    )
    new = [
        f for f in open_items if f["id"] not in prev_open and f.get("found_in_audit") == audit_id
    ]
    new_ids = {f["id"] for f in new}
    persisting = [f for f in open_items if f["id"] not in new_ids]
    fixed = [
        f
        for f in findings
        if f["status"] == "fixed" and (f["id"] in prev_open or f.get("fixed_in_audit") == audit_id)
    ]
    closed_other = [f for f in findings if f["status"] in ("wontfix", "false_positive")]

    counts = {sev: sum(1 for f in open_items if f["severity"] == sev) for sev in SEVERITY_ORDER}
    lines = [
        "# PRISM Audit Report",
        "",
        f"- Audit: `{audit_id}` · scope `{audit.get('scope', 'all')}` · depth `{audit.get('depth', 'standard')}`",
        f"- Open findings: **{len(open_items)}** "
        + "("
        + ", ".join(f"{n} {sev}" for sev, n in counts.items() if n)
        + ")"
        if open_items
        else "- Open findings: **0**",
        f"- Since last report: {len(new)} new · {len(fixed)} fixed · {len(persisting)} persisting",
        "",
        "## Summary",
        "",
        "| Severity | Open |",
        "|---|---|",
        *(f"| {sev} | {n} |" for sev, n in counts.items()),
        "",
    ]
    for title, items in (("New", new), ("Persisting", persisting)):
        if items:
            lines += [
                f"## {title} findings",
                "",
                "| ID | Severity | Category | Confidence | Title | Location |",
                "|---|---|---|---|---|---|",
                *(_row(f) for f in items),
                "",
            ]
    if fixed:
        lines += [
            "## Fixed since last report",
            "",
            *(f"- {f['id']}: {f['title']}" for f in fixed),
            "",
        ]
    if closed_other:
        lines += [
            "## Closed without fix",
            "",
            *(f"- {f['id']} ({f['status']}): {f['title']}" for f in closed_other),
            "",
        ]
    if open_items:
        lines += ["## Details", ""]
        for f in open_items:
            lines += _detail(f)
    text = "\n".join(lines).rstrip() + "\n"

    out = audit_dir(root)
    write_text(out / "REPORT.md", text)
    stamp = _safe_stamp(audit_id)
    history = out / "history"
    write_text(history / f"REPORT-{stamp}.md", text)
    write_json(history / f"findings-{stamp}.json", {"audit_id": audit_id, "findings": findings})
    data["last_report"] = audit_id
    write_findings(root, data)
    return {
        "report": (out / "REPORT.md").relative_to(root).as_posix(),
        "audit_id": audit_id,
        "open": len(open_items),
        "open_by_severity": {k: v for k, v in counts.items() if v},
        "new": [f["id"] for f in new],
        "fixed": [f["id"] for f in fixed],
        "persisting": [f["id"] for f in persisting],
    }
