"""`prism status`: consent state, index freshness, and summary counts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prism.config import load_config
from prism.consent import RepoState, repo_state
from prism.core.paths import AICONTEXT
from prism.discovery import discover
from prism.writers import load_manifest


def audit_summary(root: Path) -> dict[str, Any] | None:
    """Counts of audit findings by status and severity, or None if no audit has run."""
    path = root / AICONTEXT / "audit" / "findings.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    findings = data.get("findings", [])
    open_items = [f for f in findings if f.get("status") == "open"]
    by_sev: dict[str, int] = {}
    for f in open_items:
        by_sev[f.get("severity", "info")] = by_sev.get(f.get("severity", "info"), 0) + 1
    return {
        "open": len(open_items),
        "total": len(findings),
        "open_by_severity": dict(sorted(by_sev.items())),
        "last_report": data.get("last_report"),
    }


@dataclass
class StatusReport:
    root: str
    state: RepoState
    indexed: bool = False
    last_scan: str | None = None
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    stale_sections: list[str] = field(default_factory=list)
    drift: dict[str, int] = field(default_factory=dict)
    rank_approx: bool = False
    audit: dict[str, Any] | None = None

    @property
    def changed(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)

    @property
    def fresh(self) -> bool:
        return self.indexed and self.changed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "state": self.state.name.lower(),
            "state_label": self.state.value,
            "indexed": self.indexed,
            "fresh": self.fresh,
            "last_scan": self.last_scan,
            "changed_files": {
                "added": self.added,
                "modified": self.modified,
                "deleted": self.deleted,
            },
            "stats": self.stats,
            "stale_sections": self.stale_sections,
            "drift": self.drift,
            "rank_approx": self.rank_approx,
            "audit": self.audit,
        }


def compute_status(root: Path, check_files: bool = True) -> StatusReport:
    manifest = load_manifest(root)
    repo_id = manifest.get("repo_id") if manifest else None
    report = StatusReport(root=root.as_posix(), state=repo_state(root, repo_id))
    if manifest is None:
        return report
    report.last_scan = manifest.get("last_scan")
    report.indexed = report.last_scan is not None
    report.stats = manifest.get("stats", {})
    sections = manifest.get("drift", {}).get("sections", {})
    report.stale_sections = sorted(k for k, v in sections.items() if v.get("stale"))
    report.drift = {
        k: int(v.get("score", 0)) for k, v in sorted(sections.items()) if v.get("score")
    }
    report.rank_approx = bool(manifest.get("rank_approx"))
    report.audit = audit_summary(root)
    if not (check_files and report.indexed):
        return report
    known: dict[str, Any] = manifest.get("files", {})
    current = {f.path: f.sha256 for f in discover(root, load_config(root), known)}
    report.added = sorted(set(current) - set(known))
    report.deleted = sorted(set(known) - set(current))
    report.modified = sorted(
        p for p in set(current) & set(known) if current[p] != known[p].get("sha256")
    )
    return report
