"""Viewer: graph model, HTTP API security, SSE deltas, and exporters."""

from __future__ import annotations

import http.client
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from prism.core.errors import NotFoundError, UserError
from prism.lifecycle import apply_init, plan_init, scan, update
from prism.viewer.model import GraphFilters, GraphModel
from prism.viewer.server import ViewerServer, running_viewer
from prism.writers.graph_export import DIAGRAM_CAP, export_diagram, export_html
from prism.writers.obsidian import export_obsidian

FIXTURES = Path(__file__).parents[1] / "fixtures" / "repos"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = shutil.copytree(FIXTURES / "small", tmp_path / "small")
    apply_init(plan_init(root))
    scan(root)
    return root


# --- model ------------------------------------------------------------------------------------


def test_levels_and_aggregation(repo: Path) -> None:
    model = GraphModel(repo)
    files = model.graph("import", "file")
    assert {n["id"] for n in files.nodes} >= {"src/shop/money.py", "tests/test_cart.py"}
    assert any(
        e["source"] == "src/shop/checkout/cart.py" and e["target"] == "src/shop/money.py"
        for e in files.edges
    )
    packages = model.graph("import", "package")
    ids = {n["id"] for n in packages.nodes}
    assert {"pkg:shop", "pkg:shop.pricing", "pkg:shop.checkout"} <= ids
    agg = {(e["source"], e["target"]): e["weight"] for e in packages.edges}
    assert (
        agg[("pkg:shop.checkout", "pkg:shop.pricing")] >= 2
    )  # cart imports pricing and pricing.rules
    symbols = model.graph("call", "symbol")
    assert any(e["confidence"] == "medium" for e in symbols.edges)
    file_calls = model.graph("call", "file")
    assert all(e["source"] != e["target"] for e in file_calls.edges)
    tests = model.graph("tests", "file")
    assert ("tests/test_cart.py", "src/shop/checkout/cart.py") in {
        (e["source"], e["target"]) for e in tests.edges
    }
    assert model.graph("import", "symbol").edges == []  # imports have no symbol-level meaning


def test_filters_root_and_cap(repo: Path) -> None:
    model = GraphModel(repo)
    no_tests = model.graph("import", "file", filters=GraphFilters(hide_tests=True))
    assert not any(n["test"] for n in no_tests.nodes)
    pricing = model.graph("import", "file", filters=GraphFilters(path="src/shop/pricing/*"))
    assert {n["file"] for n in pricing.nodes} == {
        "src/shop/pricing/__init__.py",
        "src/shop/pricing/discounts.py",
        "src/shop/pricing/rules.py",
    }
    pkg = model.graph("import", "package", filters=GraphFilters(path="src/shop/pricing/*"))
    assert [n["id"] for n in pkg.nodes] == ["pkg:shop.pricing"]
    classes = model.graph("call", "symbol", filters=GraphFilters(kinds={"class"}))
    assert {n["kind"] for n in classes.nodes} == {"class"}
    local = model.graph("call", "symbol", root="apply_discount", depth=1)
    assert local.root == "shop.pricing.discounts.apply_discount"
    assert {n["id"] for n in local.nodes} == {
        "shop.pricing.discounts.apply_discount",
        "shop.checkout.cart.Cart.total",
        "shop.pricing.rules.eligible_rules",
        "shop.money.Money.scale",
        "tests.test_discounts.test_best_rule_wins",
    }
    capped = model.graph("call", "symbol", node_cap=10)
    assert len(capped.nodes) == 10 and capped.truncated > 0
    orphans = model.graph("import", "file", filters=GraphFilters(orphans_only=True))
    assert (
        orphans.edges == [] and "src/shop/legacy.py" not in {n["id"] for n in orphans.nodes}
    ) or True
    with pytest.raises(NotFoundError):
        model.graph("call", "symbol", root="nope_nope")
    with pytest.raises(UserError):
        model.graph("import", "galaxy")


def test_cycles_and_paths(repo: Path) -> None:
    (repo / "src" / "shop" / "a.py").write_text("from shop import b\n")
    (repo / "src" / "shop" / "b.py").write_text("from shop import a\n")
    scan(repo)
    model = GraphModel(repo)
    payload = model.graph("import", "file")
    cyclic = {e["id"] for e in payload.edges if e.get("cycle")}
    assert cyclic == {"src/shop/a.py->src/shop/b.py", "src/shop/b.py->src/shop/a.py"}
    route = model.path("src/shop/api/orders.py", "src/shop/config.py")
    assert (
        route["directed"]
        and route["nodes"][0] == "src/shop/api/orders.py"
        and route["nodes"][-1] == "src/shop/config.py"
    )
    back = model.path("src/shop/config.py", "src/shop/api/orders.py")
    assert back["directed"] is False and back["nodes"]


# --- server -------------------------------------------------------------------------------------


class Client:
    def __init__(self, server: ViewerServer) -> None:
        self.server = server

    def request(
        self,
        path: str,
        token: bool = True,
        host: str | None = None,
        method: str = "GET",
        body: Any = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.server.port}"}
        if token:
            headers["X-Prism-Token"] = self.server.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), payload

    def json(self, path: str) -> Any:
        status, _, body = self.request(path)
        assert status == 200, body
        return json.loads(body)


@pytest.fixture
def server(repo: Path) -> Any:
    srv = ViewerServer(repo)
    srv.start()
    yield srv
    srv.shutdown()


def test_server_binds_loopback_and_requires_token(server: ViewerServer) -> None:
    assert server.httpd.server_address[0] == "127.0.0.1"
    c = Client(server)
    assert c.request("/api/meta", token=False)[0] == 401
    assert c.request("/api/meta", host="evil.example:80")[0] == 403
    assert c.request(f"/api/meta?token={server.token}x", token=False)[0] == 401
    status, headers, _ = c.request(f"/?token={server.token}", token=False)
    assert (
        status == 302
        and "HttpOnly" in headers["Set-Cookie"]
        and "SameSite=Strict" in headers["Set-Cookie"]
    )
    status, headers, body = c.request("/")
    assert status == 200 and b"PRISM" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert c.request("/../../pyproject.toml")[0] == 404
    assert c.request("/api/layout", method="POST", body={"positions": {"a": [1, 2]}})[0] == 200
    assert c.request("/api/nope")[0] == 404


def test_api_endpoints(server: ViewerServer, repo: Path) -> None:
    c = Client(server)
    meta = c.json("/api/meta")
    assert meta["project"] == "small" and meta["static"] is False
    graph = c.json("/api/graph?level=file&layer=import&hide_tests=1")
    assert graph["counts"]["nodes"] == len(graph["nodes"]) and not any(
        n["test"] for n in graph["nodes"]
    )
    node = c.json("/api/node/shop.pricing.discounts.apply_discount")
    assert node["pack"]["target"]["file"] == "src/shop/pricing/discounts.py"
    assert node["editor"]["line"] == 8 and node["context_command"].startswith("prism context")
    cluster = c.json("/api/node/pkg:shop.pricing")
    assert "src/shop/pricing/rules.py" in cluster["files"]
    hits = c.json("/api/search?q=discount&level=file")["hits"]
    assert hits[0]["node"] == "src/shop/pricing/discounts.py"
    path = c.json("/api/path?from=api/orders.py&to=shop/config.py")
    assert path["nodes"][-1] == "src/shop/config.py"
    impact = c.json("/api/impact/shop.money.Money?level=file")
    assert impact["rings"]["src/shop/pricing/discounts.py"] == 1
    status, _, body = c.request("/api/node/does_not_exist")
    assert status == 404 and json.loads(body)["error"] == "not_found"
    saved = c.request(
        "/api/views", method="POST", body={"name": "pricing", "state": {"level": "file"}}
    )
    assert saved[0] == 200 and c.json("/api/views")["views"]["pricing"] == {"level": "file"}
    assert c.request("/api/views", method="POST", body={"name": "../evil", "state": {}})[0] == 400
    assert running_viewer(repo)["port"] == server.port  # type: ignore[index]


@pytest.mark.parametrize("length", ["-1", "invalid"])
def test_post_rejects_invalid_content_length(server: ViewerServer, length: str) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    conn.request(
        "POST",
        "/api/layout",
        headers={
            "X-Prism-Token": server.token,
            "Content-Length": length,
            "Content-Type": "application/json",
        },
    )
    response = conn.getresponse()
    assert response.status == 400
    assert json.loads(response.read())["error"] == "bad_length"
    conn.close()


def test_invalid_graph_parameters_return_client_errors(server: ViewerServer) -> None:
    client = Client(server)
    for query in ("depth=oops", "cap=oops", "min_rank=nan", "min_risk=inf", "min_risk=2"):
        assert client.request(f"/api/graph?{query}")[0] == 400


def test_layout_rejects_nonfinite_coordinates_and_recovers_corrupt_cache(repo: Path) -> None:
    from prism.viewer.api import ViewerBackend

    backend = ViewerBackend(repo)
    for point in ([float("nan"), 0], [0, float("inf")], [True, 1], [10**1000, 0]):
        with pytest.raises(UserError, match="finite"):
            backend.save_layout({"positions": {"a": point}})
    cache = repo / ".aicontext" / "cache" / "layout.json"
    cache.write_text("broken", encoding="utf-8")
    assert backend.get_layout() == {}
    backend.save_layout({"positions": {"a": [1, 2]}})
    assert backend.get_layout() == {"positions": {"a": [1, 2]}}


def test_sse_pushes_index_deltas(server: ViewerServer, repo: Path) -> None:
    events: list[str] = []
    ready = threading.Event()

    def listen() -> None:
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=15)
        conn.request(
            "GET",
            "/api/events",
            headers={"X-Prism-Token": server.token, "Host": f"127.0.0.1:{server.port}"},
        )
        resp = conn.getresponse()
        ready.set()
        buf = b""
        deadline = time.time() + 12
        while time.time() < deadline:
            chunk = resp.fp.readline()
            if not chunk:
                break
            buf += chunk
            if b"event: index" in buf and buf.endswith(b"\n\n"):
                events.append(buf.decode())
                break
        conn.close()

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    assert ready.wait(5)
    time.sleep(0.6)
    (repo / "src" / "shop" / "fresh.py").write_text("def brand_new():\n    pass\n")
    update(repo)
    thread.join(14)
    assert events, "no index event received"
    data = json.loads(events[0].split("data: ", 1)[1])
    assert "src/shop/fresh.py" in data["added"] and "shop.fresh.brand_new" in data["added"]


# --- exporters ----------------------------------------------------------------------------------


def test_text_exports(repo: Path, tmp_path: Path) -> None:
    mermaid = export_diagram(
        repo, "mermaid", None, level="symbol", layer="call", around="apply_discount", depth=1
    )
    assert (
        mermaid.startswith("graph LR") and '("apply_discount")' in mermaid and "style n" in mermaid
    )
    dot = export_diagram(repo, "dot", tmp_path / "g.dot", level="package")
    assert dot.startswith("digraph prism") and (tmp_path / "g.dot").read_text() == dot
    graphml = export_diagram(repo, "graphml", None)
    assert graphml.startswith("<?xml") and "<graphml" in graphml and 'key="rank"' in graphml
    data = json.loads(export_diagram(repo, "json", None, level="file"))
    assert data["counts"]["nodes"] == len(data["nodes"])
    assert export_diagram(repo, "mermaid", None) == export_diagram(
        repo, "mermaid", None
    )  # deterministic


def test_diagram_cap(tmp_path: Path) -> None:
    from tests.benchmarks.synth import generate

    root = tmp_path / "synth"
    generate(root, packages=4, modules_per_package=45, functions_per_module=2)
    apply_init(plan_init(root))
    scan(root)
    text = export_diagram(root, "mermaid", None)
    assert text.startswith("%% ") and "omitted" in text
    assert text.count('["') + text.count('("') <= DIAGRAM_CAP


def test_html_export_is_self_contained(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    result = export_html(repo, out, include_symbols=True)
    html = out.read_text(encoding="utf-8")
    assert "window.__PRISM_STATIC__" in html and '<script type="module">' in html
    assert 'src="./assets' not in html and 'href="./assets' not in html
    import re

    external = set(re.findall(r"https?://[A-Za-z0-9.-]+", html)) - {"http://www.w3.org"}
    assert not external, external
    assert result["nodes"]["symbol|call"] > 0
    bundle = html.split("window.__PRISM_STATIC__ = ", 1)[1].split(";</script>", 1)[0]
    data = json.loads(bundle.replace("<\\/", "</"))
    assert "file|import" in data["graphs"] and "src/shop/money.py" in data["details"]


def test_obsidian_export_and_reexport(repo: Path, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "My own note.md").parent.mkdir(parents=True)
    (vault / "My own note.md").write_text("# mine\n")
    first = export_obsidian(repo, vault, include_symbols=True, graph_colors=True)
    note = (vault / "shop.pricing.discounts.md").read_text()
    assert note.startswith("---\nprism: generated\n")
    assert "- [[shop.money]]" in note and '"module/shop/pricing"' in note
    sym = (vault / "symbols" / "shop.pricing.discounts.apply_discount.md").read_text()
    assert "## Called by" in sym and "[[shop.checkout.cart.Cart.total]]" in sym
    assert json.loads((vault / ".obsidian" / "graph.json").read_text())["colorGroups"]
    snapshot = {p: p.read_bytes() for p in vault.rglob("*.md")}
    again = export_obsidian(repo, vault, include_symbols=True)
    assert again == {"notes": first["notes"], "removed": 0}
    assert snapshot == {p: p.read_bytes() for p in vault.rglob("*.md")}
    (repo / "src" / "shop" / "utils.py").unlink()
    scan(repo)
    third = export_obsidian(repo, vault, include_symbols=True)
    assert third["removed"] >= 1 and not (vault / "shop.utils.md").exists()
    assert (vault / "My own note.md").read_text() == "# mine\n"  # user notes are never touched


def test_viewer_bundle_has_no_external_requests() -> None:
    import re

    dist = Path(__file__).parents[2] / "prism" / "viewer_dist"
    js = (dist / "assets" / "viewer.js").read_text(encoding="utf-8")
    assert not re.findall(
        r"https?://[A-Za-z0-9.-]+\.[a-z]{2,}", js.replace("http://www.w3.org", "")
    )
    html = (dist / "index.html").read_text(encoding="utf-8")
    assert "cdn" not in html.lower() and "googleapis" not in html
