"""Local workspace services. Uses the existing index; never edits repository source."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from prism.core.errors import NotFoundError, UserError
from prism.core.paths import AICONTEXT
from prism.navigator.api import op_task
from prism.navigator.freshness import refresh_if_stale
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import MAX_BUDGET, MIN_BUDGET
from prism.viewer.live import LiveRunner
from prism.writers.activity import quiet_activity
from prism.writers.json_writer import write_json
from prism.writers.manifest import load_manifest

_ID = re.compile(r"^[a-f0-9]{32}$")
_TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")


def normalized_usage(records: Any) -> dict[str, int] | None:
    """Reconcile actual response counters; cached input is a subset, reasoning is included."""
    if records is None or records == []:
        return None
    if not isinstance(records, list):
        raise UserError("usage_records must be a list or null")
    seen: dict[str, dict[str, int]] = {}
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("response_id"), str):
            raise UserError("Usage records need a response_id")
        if not row["response_id"] or row.get("measurement") != "provider":
            raise UserError("Usage records must identify actual provider measurements")
        values: dict[str, int] = {}
        for key in _TOKEN_KEYS:
            value = row.get(key)
            if type(value) is not int or value < 0:
                raise UserError("Token counters must be nonnegative integers")
            values[key] = value
        if values["cached_input_tokens"] > values["input_tokens"]:
            raise UserError("Cached input cannot exceed input")
        if values["total_tokens"] != values["input_tokens"] + values["output_tokens"]:
            raise UserError("Total tokens must equal input plus output")
        old = seen.get(row["response_id"])
        if old is not None and old != values:
            raise UserError("Conflicting duplicate response counters")
        seen[row["response_id"]] = values
    totals = {key: sum(row[key] for row in seen.values()) for key in _TOKEN_KEYS}
    totals["uncached_input_tokens"] = totals["input_tokens"] - totals["cached_input_tokens"]
    totals["fresh_tokens"] = totals["uncached_input_tokens"] + totals["output_tokens"]
    return totals


def validate_report(data: Any) -> dict[str, Any]:
    """Validate the dashboard's v1 evidence format, never import percentages as proof."""
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
    ):
        raise UserError("Expected dashboard report schema_version 1")
    spec = data.get("configuration")
    if not isinstance(spec, dict):
        raise UserError("Missing configuration")
    for key in ("repository", "source_commit", "task", "host", "model", "reasoning", "delivery"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise UserError(f"configuration.{key} must be a nonempty string")
    if not re.fullmatch(r"[a-fA-F0-9]{40,64}", spec["source_commit"]):
        raise UserError("source_commit must be a full Git revision")
    arms = data.get("arms")
    if not isinstance(arms, dict) or set(arms) != {"without", "with"}:
        raise UserError("Exactly two arms, without and with, are required")
    result: dict[str, Any] = {}
    reasons: list[str] = []
    check_sets: dict[str, list[tuple[str, str]]] = {}
    response_ids: dict[str, set[str]] = {}
    for name, arm in arms.items():
        if not isinstance(arm, dict):
            raise UserError("Each arm must be an object")
        if arm.get("status") not in ("completed", "failed", "interrupted", "cancelled"):
            raise UserError("Invalid arm status")
        if not isinstance(arm.get("configuration"), dict) or arm["configuration"] != spec:
            reasons.append(f"{name}: effective configuration does not match")
        checks = arm.get("checks")
        if not isinstance(checks, list):
            raise UserError("checks must be a list")
        if not checks:
            reasons.append(f"{name}: independent checks missing")
            checks = []
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get("name"), str):
                raise UserError("Checks need a name")
            if type(check.get("passed")) is not bool or check.get("independent") is not True:
                reasons.append(f"{name}: independent verification incomplete")
            digest = check.get("evaluator_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                reasons.append(f"{name}: evaluator checksum missing or invalid")
        check_sets[name] = sorted((c["name"], str(c.get("evaluator_sha256", ""))) for c in checks)
        if len({c["name"] for c in checks}) != len(checks):
            reasons.append(f"{name}: duplicate check names")
        passed = (
            bool(checks)
            and all(c.get("passed") is True and c.get("independent") is True for c in checks)
            and arm["status"] == "completed"
        )
        usage = normalized_usage(arm.get("usage_records"))
        response_ids[name] = {r["response_id"] for r in arm.get("usage_records") or []}
        if usage is None:
            reasons.append(f"{name}: provider usage unavailable")
        elif (
            not isinstance(arm.get("session_usage"), dict)
            or any(type(arm["session_usage"].get(key)) is not int for key in _TOKEN_KEYS)
            or arm["session_usage"] != {k: usage[k] for k in _TOKEN_KEYS}
        ):
            reasons.append(f"{name}: response/session totals do not reconcile")
        if not passed:
            reasons.append(f"{name}: solution has not passed independent checks")
        for key in ("patch", "trace"):
            if not isinstance(arm.get(key, ""), str):
                raise UserError(f"{key} must be text")
        seconds = arm.get("elapsed_seconds")
        if seconds is not None and (
            type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
        ):
            raise UserError("elapsed_seconds must be finite and nonnegative")
        result[name] = {"passed": passed, "usage": usage}
    if check_sets["without"] != check_sets["with"]:
        reasons.append("Independent check sets differ")
    if response_ids["without"] & response_ids["with"]:
        reasons.append("The two arms reuse provider response identities")
    evidence = data.get("evidence", {})
    if not isinstance(evidence, dict):
        raise UserError("evidence must be an object")
    for key in ("isolation_verified", "baseline_prism_absent", "matching_source_verified"):
        if evidence.get(key) is not True:
            reasons.append(f"{key} not recorded")
    if "hook" in spec["delivery"] and evidence.get("hook_context_delivered") is not True:
        reasons.append("Automatic hook context delivery not recorded")
    eligible = not reasons
    savings: dict[str, float | None] = {"total": None, "fresh": None}
    if eligible:
        for label, key in (("total", "total_tokens"), ("fresh", "fresh_tokens")):
            baseline = result["without"]["usage"][key]
            if baseline:
                savings[label] = (baseline - result["with"]["usage"][key]) / baseline * 100
    return {"arms": result, "comparable": eligible, "reasons": reasons, "savings": savings}


class DashboardService:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.cache = self.root / AICONTEXT / "cache" / "dashboard"
        self._lock = threading.Lock()
        self.live = LiveRunner(self.root, self.cache / "live")
        self._job: dict[str, Any] | None = None
        self._sandbox_job: dict[str, Any] | None = None
        for filename, attribute in (
            ("index-job.json", "_job"),
            ("sandbox-job.json", "_sandbox_job"),
        ):
            try:
                job = json.loads((self.cache / filename).read_text(encoding="utf-8"))
                if not isinstance(job, dict) or job.get("state") not in (
                    "running",
                    "completed",
                    "failed",
                    "interrupted",
                ):
                    continue
                if job["state"] == "running":
                    job.update(
                        state="interrupted",
                        error="Server restarted before this operation completed; it was not automatically rerun",
                    )
                    write_json(self.cache / filename, job)
                setattr(self, attribute, job)
            except (OSError, ValueError):
                pass

    def _git(self, *args: str) -> str | None:
        try:
            r = subprocess.run(
                ["git", *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def status(self) -> dict[str, Any]:
        manifest = load_manifest(self.root) or {}
        from prism.status import compute_status

        health = compute_status(self.root).to_dict()
        return {
            "project": self.root.name,
            "root": str(self.root),
            "commit": self._git("rev-parse", "HEAD"),
            "branch": self._git("branch", "--show-current"),
            "dirty": bool(self._git("status", "--porcelain")),
            "stats": manifest.get("stats", {}),
            "last_scan": manifest.get("last_scan"),
            "index_revision": hashlib.sha256(
                json.dumps(manifest.get("artifacts", {}), sort_keys=True).encode()
            ).hexdigest(),
            "job": self.job(),
            "consent": health["state_label"],
            "fresh": health["fresh"],
            "changed_files": health["changed_files"],
        }

    def hosts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": ident,
                "name": name,
                "installed": bool(shutil.which(executable)),
                "managed": False,
                "reason": "Managed execution requires a validated isolation and provider-usage adapter. Use your installed host for manual work or import recorded evidence.",
                "handoff": True,
            }
            for ident, name, executable in (
                ("codex", "Codex", "codex"),
                ("claude", "Claude Code", "claude"),
                ("antigravity", "Antigravity", "antigravity"),
            )
        ]

    def preview(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise UserError("Expected a JSON object")
        query = body.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 12000:
            raise UserError("Enter a task between 1 and 12000 characters")
        budget = body.get("budget", 2000)
        if budget is not None and (
            type(budget) is not int or not MIN_BUDGET <= budget <= MAX_BUDGET
        ):
            raise UserError(
                f"Budget must be automatic or an integer between {MIN_BUDGET} and {MAX_BUDGET}"
            )
        mode = body.get("mode", "auto")
        if mode not in ("auto", "code", "overview"):
            raise UserError("Mode must be auto, code or overview")
        with self._lock:
            if self._job and self._job["state"] == "running":
                raise UserError("Wait for the index refresh to complete")
            refresh_if_stale(self.root)  # Same consent/freshness policy as CLI and MCP.
            store = IndexStore.open(self.root)
            try:
                # No agent session or delivery memory; ordinary core retrieval, no new engine.
                with quiet_activity():
                    packet = op_task(
                        store,
                        query.strip(),
                        budget=budget,
                        mode=mode,
                        session=None,
                        use_cache=False,
                    )
                manifest = store.manifest
            finally:
                store.close()
        from prism.navigator.task_pack import render_task

        return {
            "packet": packet,
            "text": render_task(packet),
            "measurement": "estimated_context",
            "index_revision": hashlib.sha256(
                json.dumps(manifest.get("artifacts", {}), sort_keys=True).encode()
            ).hexdigest(),
            "last_scan": manifest.get("last_scan"),
        }

    def refresh(self) -> dict[str, Any]:
        with self._lock:
            if self._job and self._job["state"] == "running":
                return dict(self._job)
            self._job = {"id": uuid.uuid4().hex, "state": "running", "started": time.time()}
            write_json(self.cache / "index-job.json", self._job)
            thread = threading.Thread(target=self._refresh, daemon=True)
            thread.start()
            return dict(self._job)

    def _refresh(self) -> None:
        from prism.lifecycle import scan

        try:
            manifest = scan(self.root)
            update = {"state": "completed", "stats": manifest["stats"]}
        except Exception as exc:
            update = {"state": "failed", "error": str(exc)}
        with self._lock:
            assert self._job is not None
            self._job.update(update, finished=time.time())
            write_json(self.cache / "index-job.json", self._job)

    def job(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._job) if self._job else None

    def prepare_sandboxes(self, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("task"), str)
            or not body["task"].strip()
            or len(body["task"]) > 12000
        ):
            raise UserError("Enter one task before preparing repository copies")
        with self._lock:
            if self._sandbox_job and self._sandbox_job["state"] == "running":
                return dict(self._sandbox_job)
            self._sandbox_job = {"id": uuid.uuid4().hex, "state": "running", "started": time.time()}
            write_json(self.cache / "sandbox-job.json", self._sandbox_job)
            threading.Thread(
                target=self._prepare_sandboxes, args=(body["task"].strip(),), daemon=True
            ).start()
            return dict(self._sandbox_job)

    def _prepare_sandboxes(self, task: str) -> None:
        from prism.viewer.sandboxes import prepare_pair

        try:
            result = prepare_pair(self.root, task)
            update = {"state": "completed", "preparation": result}
        except Exception as exc:
            update = {"state": "failed", "error": str(exc)}
        with self._lock:
            assert self._sandbox_job is not None
            self._sandbox_job.update(update, finished=time.time())
            write_json(self.cache / "sandbox-job.json", self._sandbox_job)

    def sandbox_job(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._sandbox_job) if self._sandbox_job else None

    def import_run(self, body: Any) -> dict[str, Any]:
        summary = validate_report(body)
        ident = uuid.uuid4().hex
        record = {
            "id": ident,
            "imported_at": time.time(),
            "provenance": "Imported; evidence assertions supplied by report author",
            "report": body,
            "summary": summary,
        }
        write_json(self.cache / "runs" / f"{ident}.json", record)
        return record

    def runs(self) -> list[dict[str, Any]]:
        rows = []
        for path in (self.cache / "runs").glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                row["summary"] = validate_report(row["report"])
                rows.append(
                    {k: row[k] for k in ("id", "imported_at", "provenance", "summary")}
                    | {"configuration": row["report"]["configuration"]}
                )
            except (OSError, ValueError, KeyError, TypeError, UserError):
                continue
        return sorted(rows, key=lambda row: row["imported_at"], reverse=True)

    def run(self, ident: str) -> dict[str, Any]:
        if not _ID.fullmatch(ident):
            raise UserError("Invalid run ID")
        try:
            value = json.loads((self.cache / "runs" / f"{ident}.json").read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid saved run")
            value["summary"] = validate_report(value.get("report"))
            return value
        except (OSError, ValueError, UserError) as exc:
            raise NotFoundError("Run not found") from exc
