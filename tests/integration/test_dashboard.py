"""Dashboard transport, truthful accounting and retrieval parity."""

from __future__ import annotations

import copy
import http.client
import json
import shutil
import subprocess
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from prism.core.errors import UserError
from prism.lifecycle import apply_init, plan_init, scan, set_paused
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore
from prism.viewer.api import ViewerBackend
from prism.viewer.dashboard import DashboardService, normalized_usage, validate_report
from prism.viewer.model import GraphModel
from prism.viewer.sandboxes import prepare_pair
from prism.viewer.server import ViewerServer
from prism.writers.activity import activity_path
from prism.writers.worklog import worklog_dir


@pytest.fixture
def root(tmp_path: Path) -> Path:
    repo = shutil.copytree(Path(__file__).parents[1] / "fixtures/repos/small", tmp_path / "repo")
    apply_init(plan_init(repo))
    scan(repo)
    return repo


def report() -> dict:
    spec = {
        "repository": "small",
        "source_commit": "a" * 40,
        "task": "Fix total",
        "host": "codex",
        "model": "recorded-model",
        "reasoning": "medium",
        "delivery": "hook",
    }

    def arm(tokens: int) -> dict:
        counters = {
            "input_tokens": tokens,
            "cached_input_tokens": 20,
            "output_tokens": 10,
            "total_tokens": tokens + 10,
        }
        return {
            "configuration": copy.deepcopy(spec),
            "status": "completed",
            "checks": [
                {
                    "name": "total regression",
                    "passed": True,
                    "independent": True,
                    "evaluator_sha256": "b" * 64,
                }
            ],
            "usage_records": [
                {"response_id": f"response-{tokens}", "measurement": "provider", **counters}
            ],
            "session_usage": counters,
            "elapsed_seconds": 1.0,
            "patch": "",
            "trace": "",
        }

    return {
        "schema_version": 1,
        "configuration": spec,
        "arms": {"without": arm(100), "with": arm(60)},
        "evidence": {
            "isolation_verified": True,
            "baseline_prism_absent": True,
            "matching_source_verified": True,
            "hook_context_delivered": True,
        },
    }


def test_actual_usage_duplicate_and_reasoning_accounting() -> None:
    row = {
        "response_id": "r",
        "measurement": "provider",
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "output_tokens": 20,
        "total_tokens": 120,
        "reasoning_output_tokens": 10,
    }
    usage = normalized_usage([row, row])
    assert usage is not None
    assert usage["total_tokens"] == 120 and usage["fresh_tokens"] == 80
    with pytest.raises(UserError, match="Conflicting"):
        normalized_usage([row, row | {"output_tokens": 21, "total_tokens": 121}])
    with pytest.raises(UserError, match="provider"):
        normalized_usage([row | {"measurement": "estimate"}])


def test_report_reconciliation_and_failure_never_show_savings() -> None:
    data = report()
    result = validate_report(data)
    assert result["comparable"]
    assert result["savings"]["total"] == pytest.approx(40 / 110 * 100)
    for bad in ["check", "usage", "settings", "hook"]:
        changed = copy.deepcopy(data)
        if bad == "check":
            changed["arms"]["with"]["checks"][0]["passed"] = False
        if bad == "usage":
            changed["arms"]["with"]["session_usage"]["total_tokens"] = 999
        if bad == "settings":
            changed["arms"]["with"]["configuration"]["model"] = "other"
        if bad == "hook":
            changed["evidence"]["hook_context_delivered"] = False
        summary = validate_report(changed)
        assert not summary["comparable"] and summary["savings"]["total"] is None


def test_report_rejects_reused_responses_and_fake_session_types() -> None:
    data = report()
    data["arms"]["with"]["usage_records"][0]["response_id"] = "response-100"
    assert not validate_report(data)["comparable"]
    data = report()
    data["arms"]["with"]["session_usage"]["output_tokens"] = 10.0
    assert not validate_report(data)["comparable"]
    data["schema_version"] = True
    with pytest.raises(UserError):
        validate_report(data)
    with pytest.raises(UserError):
        normalized_usage({"total_tokens": 100})


def test_same_check_name_with_different_evaluator_is_not_comparable() -> None:
    data = report()
    data["arms"]["with"]["checks"][0]["evaluator_sha256"] = "c" * 64
    assert not validate_report(data)["comparable"]
    data["arms"]["with"]["checks"][0].pop("evaluator_sha256")
    assert not validate_report(data)["comparable"]


def test_saving_increases_and_zero_baseline_are_honest() -> None:
    data = report()
    data["arms"]["without"], data["arms"]["with"] = data["arms"]["with"], data["arms"]["without"]
    assert validate_report(data)["savings"]["total"] < 0
    data = report()
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
        data["arms"]["without"]["usage_records"][0][key] = 0
        data["arms"]["without"]["session_usage"][key] = 0
    assert validate_report(data)["savings"]["total"] is None


def test_context_uses_core_without_delivery_memory(root: Path) -> None:
    service = DashboardService(root)
    query = "Fix Cart.total discount calculation"
    preview = service.preview({"query": query, "budget": 2000})
    store = IndexStore.open(root)
    try:
        core = op_task(store, query, budget=2000, session=None, use_cache=False)
    finally:
        store.close()
    assert preview["packet"]["blocks"] == core["blocks"]
    assert preview["text"] and preview["measurement"] == "estimated_context"
    with pytest.raises(UserError):
        service.preview({"query": query, "budget": True})


def test_dashboard_cli_and_mcp_task_source_parity(root: Path) -> None:
    from prism.mcp.server import PrismTools

    query = "Fix Cart.total discount calculation"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "prism",
            "task",
            query,
            "--root",
            str(root),
            "--budget",
            "2000",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    cli = json.loads(process.stdout)
    tools = PrismTools(root)
    try:
        mcp = tools.prism_task(query, budget=2000, repeat=True)
        dashboard = DashboardService(root).preview({"query": query, "budget": 2000})["packet"]
        assert "error" not in mcp
        assert cli["blocks"] == dashboard["blocks"] == mcp["blocks"]
        assert cli["confidence"] == dashboard["confidence"] == mcp["confidence"]
    finally:
        if tools._store is not None:
            tools._store.close()


def test_preview_refreshes_recent_source_and_does_not_log_agent_delivery(root: Path) -> None:
    service = DashboardService(root)
    before_activity = activity_path(root).read_bytes() if activity_path(root).exists() else b""
    before_logs = {p.name: p.read_bytes() for p in worklog_dir(root).glob("*") if p.is_file()}
    before_revision = service.status()["index_revision"]
    changed = root / "src/shop/money.py"
    changed.write_text(
        changed.read_text() + "\n\ndef dashboard_sync_probe():\n    return 'fresh-source-proof'\n"
    )
    pack = service.preview({"query": "dashboard_sync_probe", "budget": 2000})
    assert "fresh-source-proof" in pack["text"]
    assert pack["index_revision"] != before_revision
    assert service.status()["fresh"]
    assert (
        activity_path(root).read_bytes() if activity_path(root).exists() else b""
    ) == before_activity
    assert {
        p.name: p.read_bytes() for p in worklog_dir(root).glob("*") if p.is_file()
    } == before_logs


def test_graph_backend_shares_updated_core_index(root: Path) -> None:
    backend = ViewerBackend(root)
    before = backend.graph({"level": "symbol", "layer": "call"})
    changed = root / "src/shop/money.py"
    changed.write_text(
        changed.read_text() + "\n\ndef synchronized_graph_symbol():\n    return 42\n"
    )
    DashboardService(root).preview({"query": "synchronized_graph_symbol", "budget": 2000})
    after = backend.graph({"level": "symbol", "layer": "call"})
    assert len(after["nodes"]) > len(before["nodes"])
    core = GraphModel(root).graph("call", "symbol").to_dict()
    assert {(node["id"], node["file"]) for node in after["nodes"]} == {
        (node["id"], node["file"]) for node in core["nodes"]
    }


def test_preview_respects_paused_automatic_refresh(root: Path) -> None:
    service = DashboardService(root)
    before = service.status()["index_revision"]
    set_paused(root, True)
    file = root / "src/shop/money.py"
    file.write_text(file.read_text() + "\n\ndef paused_probe():\n    return 9\n")
    service.preview({"query": "paused_probe", "budget": 2000})
    assert service.status()["index_revision"] == before
    assert not service.status()["fresh"]


def test_refresh_job_survives_recreation_and_source_is_unchanged(root: Path) -> None:
    service = DashboardService(root)
    source = {str(p): p.read_bytes() for p in root.rglob("*.py")}
    service.refresh()
    deadline = time.monotonic() + 20
    while service.job()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert service.job()["state"] == "completed"
    assert service.job()["stats"]["files"] > 0
    assert DashboardService(root).job() == service.job()
    assert source == {str(p): p.read_bytes() for p in root.rglob("*.py")}
    from prism.writers.json_writer import write_json

    write_json(service.cache / "index-job.json", {"id": "lost", "state": "running"})
    assert DashboardService(root).job()["state"] == "interrupted"


def test_two_prepared_copies_pin_commit_preserve_original_and_only_index_with(root: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init")
    git("add", "src", "tests")
    (root / ".env").write_text("DO_NOT_COPY=secret")
    (root / ".codex").mkdir(exist_ok=True)
    (root / ".codex/config.toml").write_text("hooks = true")
    git("add", "-f", ".env", ".codex/config.toml")
    git(
        "-c",
        "user.name=UI test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    original = root / "src/shop/money.py"
    committed = original.read_bytes()
    original.write_bytes(committed + b"\n# keep my uncommitted work\n")
    before = original.read_bytes()
    preparation = prepare_pair(root, "Test matching sources")
    baseline = Path(preparation["arms"]["without"])
    indexed = Path(preparation["arms"]["with"])
    assert original.read_bytes() == before
    assert (baseline / "src/shop/money.py").read_bytes() == committed
    assert (indexed / "src/shop/money.py").read_bytes() == committed
    assert baseline.parent == indexed.parent and not baseline.is_relative_to(root)
    assert not (baseline / ".aicontext").exists()
    assert (indexed / ".aicontext/manifest.json").exists()
    for path in (baseline, indexed):
        assert not (path / ".env").exists()
        assert not (path / ".codex").exists()
    assert preparation["matching_source_verified"] and preparation["baseline_prism_absent"]
    assert not preparation["isolation_verified"] and preparation["agent_sessions_started"] == 0
    assert preparation["indexing"]["llm_tokens"] == 0


def test_report_persistence_and_path_boundary(root: Path) -> None:
    service = DashboardService(root)
    saved = service.import_run(report())
    assert service.run(saved["id"])["report"] == report()
    assert service.runs()[0]["id"] == saved["id"]
    with pytest.raises(UserError):
        service.run("../../secret")


def test_http_dashboard_authenticated_and_cross_origin_blocked(root: Path) -> None:
    server = ViewerServer(root)
    server.start()

    def request(
        path: str,
        method: str = "GET",
        data: dict | None = None,
        token: bool = True,
        origin: str | None = None,
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=15)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Prism-Token"] = server.token
        if origin:
            headers["Origin"] = origin
        conn.request(
            method, path, body=json.dumps(data) if data is not None else None, headers=headers
        )
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    try:
        assert request("/api/dashboard/status", token=False)[0] == 401
        assert request("/api/dashboard/status")[0] == 200
        assert request("/dashboard.html")[0] == 200
        assert (
            request("/api/dashboard/runs", "POST", report(), origin="http://evil.example")[0] == 403
        )
        code, body = request("/api/dashboard/runs", "POST", report())
        assert code == 201 and json.loads(body)["summary"]["comparable"]
        assert (
            request("/api/dashboard/context", "POST", {"query": "Cart.total", "budget": 2000})[0]
            == 200
        )
        assert request("/api/graph")[0] == 200
    finally:
        server.shutdown()


def test_multiple_workspaces_do_not_overwrite_browser_authentication(root: Path) -> None:
    first, second = ViewerServer(root), ViewerServer(root)
    first.start()
    second.start()
    cookies: dict[str, str] = {}
    try:
        for server in (first, second):
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
            connection.request("GET", f"/dashboard.html?token={server.token}")
            response = connection.getresponse()
            assert response.status == 302
            cookie = SimpleCookie()
            cookie.load(response.getheader("Set-Cookie"))
            cookies.update({name: item.value for name, item in cookie.items()})
            response.read()
            connection.close()
        assert len(cookies) == 2
        for server in (first, second):
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
            connection.request(
                "GET",
                "/api/meta",
                headers={"Cookie": "; ".join(f"{key}={value}" for key, value in cookies.items())},
            )
            response = connection.getresponse()
            assert response.status == 200
            response.read()
            connection.close()
    finally:
        first.shutdown()
        second.shutdown()
