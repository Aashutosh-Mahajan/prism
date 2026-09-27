"""`prism audit plan`: a prioritized, evidence-oriented plan for the host agent.

Target score (CLAUDE.md 10.3) = risk + centrality + blast radius + recency
+ static smells + open prior findings. Depth caps the number of targets.
Starting a plan opens a new audit run that later `record` calls attach to.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from prism import SCHEMA_VERSION
from prism.audit.store import load_findings, plan_path, write_findings
from prism.audit.toolchain_detect import detect_toolchain
from prism.core.errors import IndexMissingError, UserError
from prism.core.paths import AICONTEXT
from prism.writers.json_writer import write_json
from prism.writers.manifest import now_iso

DEPTH_CAPS = {"quick": 10, "standard": 30, "deep": 100}
UNTESTED_CAP = 20
SMELLS_CAP = 60
DEAD_CAP = 40
W_RISK, W_CENTRALITY, W_BLAST, W_RECENCY, W_FINDINGS = 3.0, 2.0, 1.5, 1.0, 1.5
# Smells that usually indicate a real defect weigh more than hygiene smells.
SMELL_WEIGHTS = {
    "dangerous_call": 2.0,
    "sql_string_formatting": 2.0,
    "hardcoded_secret": 2.0,
    "missing_await": 1.75,
    "bare_except": 1.25,
    "swallowed_exception": 1.25,
    "mutable_default": 1.5,
    "unreachable_code": 1.0,
    "broad_except": 0.75,
    "long_function": 0.5,
    "todo": 0.25,
    "unused_import": 0.25,
}
SMELL_CAP = 4.0


def smell_score(smells: list[dict[str, Any]]) -> float:
    return min(SMELL_CAP, sum(SMELL_WEIGHTS.get(x["kind"], 0.5) for x in smells))


def _read(root: Path, name: str) -> dict[str, Any]:
    path = root / AICONTEXT / name
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _git_lines(root: Path, *args: str) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def default_base(root: Path) -> str | None:
    for ref in ("origin/main", "origin/master", "main", "master"):
        base = _git_lines(root, "merge-base", "HEAD", ref)
        if base:
            return base[0]
    return None


def changed_files(root: Path, since: str | None) -> set[str]:
    """Files changed since `since` (committed), plus uncommitted and untracked changes."""
    files: set[str] = set()
    ref = since or default_base(root)
    if ref:
        committed = _git_lines(root, "diff", "--name-only", "--relative", f"{ref}...HEAD")
        if committed is None:
            raise UserError(f"cannot diff against '{ref}' (is it a valid git ref?)")
        files.update(committed)
    for args in (
        ("diff", "--name-only", "--relative"),
        ("diff", "--name-only", "--relative", "--cached"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        files.update(_git_lines(root, *args) or [])
    return files


def _in_scope(path: str, mode: str, scope_path: str | None, changed: set[str] | None) -> bool:
    if mode == "all":
        return True
    if mode == "changed":
        return changed is not None and path in changed
    assert scope_path is not None
    prefix = scope_path.strip("/").replace("\\", "/")
    return path == prefix or path.startswith(prefix + "/")


def build_plan(
    root: Path, scope: str = "all", since: str | None = None, depth: str = "standard"
) -> dict[str, Any]:
    if depth not in DEPTH_CAPS:
        raise UserError(f"depth must be one of {', '.join(DEPTH_CAPS)}")
    symbols_doc = _read(root, "symbols.json")
    if not symbols_doc:
        raise IndexMissingError("no index; run `prism scan` (or `prism update`) first")
    health = _read(root, "health.json")
    blast = _read(root, "blast_radius.json")
    git = _read(root, "git_intelligence.json")
    tests_map = _read(root, "tests_map.json")

    mode = scope if scope in ("all", "changed") else "path"
    scope_path = None if mode != "path" else scope
    if mode == "path" and not (root / scope).exists():
        raise UserError(f"scope path '{scope}' does not exist")
    changed = changed_files(root, since) if mode == "changed" else None

    test_files = set(tests_map.get("test_files", []))
    tested = set(tests_map.get("by_symbol", {}))
    findings_data = load_findings(root)
    open_findings = [f for f in findings_data["findings"] if f.get("status") == "open"]
    findings_by_key: dict[str, list[str]] = {}
    for f in open_findings:
        for key in (f.get("symbol"), f.get("file")):
            if key:
                findings_by_key.setdefault(key, []).append(f["id"])

    symbols = [
        s
        for s in symbols_doc.get("symbols", [])
        if s["kind"] != "class"
        and s["file"] not in test_files
        and _in_scope(s["file"], mode, scope_path, changed)
    ]
    max_rank = max((s["rank"] for s in symbols), default=0.0) or 1.0
    blast_syms: dict[str, Any] = blast.get("symbols", {})
    max_blast = max((v["count"] for v in blast_syms.values()), default=0) or 1
    last_changed: dict[str, int] = git.get("last_changed", {})
    newest = max(last_changed.values(), default=0)
    smells_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for path, entry in health.get("files", {}).items():
        for smell in entry.get("smells", []):
            key = smell.get("symbol") or path
            smells_by_symbol.setdefault(key, []).append({**smell, "file": path})

    targets = []
    for s in symbols:
        sh = health.get("symbols", {}).get(s["id"], {})
        risk = float(sh.get("risk", 0.0))
        centrality = s["rank"] / max_rank
        b = blast_syms.get(s["id"], {}).get("count", 0)
        blast_score = math.log1p(b) / math.log1p(max_blast)
        age_days = (newest - last_changed.get(s["file"], newest)) / 86400 if newest else None
        recency = (
            1.0
            if age_days is not None and age_days <= 30
            else (0.5 if age_days is not None and age_days <= 90 else 0.0)
        )
        smells = smells_by_symbol.get(s["id"], [])
        prior = findings_by_key.get(s["id"], [])
        score = (
            W_RISK * risk
            + W_CENTRALITY * centrality
            + W_BLAST * blast_score
            + W_RECENCY * recency
            + smell_score(smells)
            + W_FINDINGS * len(prior)
        )
        reasons = list(sh.get("reasons", []))
        if b:
            reasons.append(f"blast radius: {b} files")
        if smells:
            reasons.append("smells: " + ", ".join(sorted({x["kind"] for x in smells})))
        if prior:
            reasons.append("open findings: " + ", ".join(prior))
        if mode == "changed":
            reasons.append("changed in scope")
        if recency and git.get("available") and mode != "changed":
            reasons.append("recently changed")
        targets.append(
            {
                "target": s["id"],
                "kind": s["kind"],
                "file": s["file"],
                "lines": s["lines"],
                "score": round(score, 3),
                "reasons": reasons,
                "context": f"prism context {s['id']} --budget 2000",
            }
        )
    # Module-level smells (e.g. a hardcoded secret in a settings file) become file targets.
    for path, entry in sorted(health.get("files", {}).items()):
        if path in test_files or not _in_scope(path, mode, scope_path, changed):
            continue
        loose = [x for x in entry.get("smells", []) if not x.get("symbol")]
        weighty = [x for x in loose if SMELL_WEIGHTS.get(x["kind"], 0.5) >= 1.0]
        if not weighty:
            continue
        prior = findings_by_key.get(path, [])
        targets.append(
            {
                "target": path,
                "kind": "file",
                "file": path,
                "lines": [min(x["line"] for x in loose), max(x["line"] for x in loose)],
                "score": round(smell_score(loose) + W_FINDINGS * len(prior), 3),
                "reasons": ["module-level smells: " + ", ".join(sorted({x["kind"] for x in loose}))]
                + (["open findings: " + ", ".join(prior)] if prior else []),
                "context": f"prism context {path} --budget 2000",
            }
        )
    targets.sort(key=lambda t: (-t["score"], t["target"]))
    targets = targets[: DEPTH_CAPS[depth]]

    scoped_smells = sorted(
        (
            {**smell, "file": path}
            for path, entry in health.get("files", {}).items()
            if _in_scope(path, mode, scope_path, changed)
            for smell in entry.get("smells", [])
        ),
        key=lambda x: (x["file"], x["line"], x["kind"]),
    )
    dead = [
        d for d in health.get("dead_code", []) if _in_scope(d["file"], mode, scope_path, changed)
    ]
    untested = sorted(
        (
            s
            for s in symbols
            if s["visibility"] == "public" and s["called_by"] and s["id"] not in tested
        ),
        key=lambda s: (-s["rank"], s["id"]),
    )[:UNTESTED_CAP]
    reverify = [
        {
            "id": f["id"],
            "title": f["title"],
            "file": f["file"],
            "symbol": f.get("symbol"),
            "evidence_command": (f.get("evidence") or {}).get("command"),
        }
        for f in open_findings
        if _in_scope(f["file"], mode, scope_path, changed)
    ]

    audit_id = now_iso()
    previous_id = str((findings_data.get("current_audit") or {}).get("id") or "")
    if previous_id.split("~")[0] == audit_id:  # two audits within one second
        suffix = int(previous_id.split("~")[1]) + 1 if "~" in previous_id else 2
        audit_id = f"{audit_id}~{suffix}"
    findings_data["current_audit"] = {
        "id": audit_id,
        "scope": scope,
        "since": since,
        "depth": depth,
    }
    write_findings(root, findings_data)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "audit_id": audit_id,
        "scope": {
            "mode": mode,
            "path": scope_path,
            "since": since,
            "files": sorted(changed) if changed is not None else None,
        },
        "depth": depth,
        "toolchain": detect_toolchain(root),
        "targets": targets,
        "smells": scoped_smells[:SMELLS_CAP],
        "smells_omitted": max(0, len(scoped_smells) - SMELLS_CAP),
        "dead_code": dead[:DEAD_CAP],
        "untested": [{"id": s["id"], "file": s["file"], "lines": s["lines"]} for s in untested],
        "reverify": reverify,
        "record_with": "prism audit record --json <finding.json>",
    }
    write_json(plan_path(root), plan)
    return plan
