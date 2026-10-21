"""Several projects in one dashboard: adding, switching and per-project routing."""

from __future__ import annotations

import http.client
import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from prism.core.errors import NotFoundError, UserError
from prism.lifecycle import apply_init, plan_init, scan
from prism.viewer.projects import ProjectManager
from prism.viewer.server import Runtime, ViewerServer

FIXTURES = Path(__file__).parents[1] / "fixtures/repos"


def make_repo(tmp_path: Path, fixture: str, name: str, index: bool = True) -> Path:
    repo = shutil.copytree(FIXTURES / fixture, tmp_path / name)
    if index:
        apply_init(plan_init(repo))
        scan(repo)
    return repo


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_CONFIG_HOME", str(tmp_path / "config"))


def test_add_validate_persist_and_remove(tmp_path: Path) -> None:
    first = make_repo(tmp_path, "small", "first")
    second = make_repo(tmp_path, "tiny", "second", index=False)
    manager = ProjectManager(first, Runtime)
    assert [p["name"] for p in manager.projects()] == ["first"]
    for bad in ("", "relative/path", str(tmp_path / "nope"), tmp_path.anchor):
        with pytest.raises(UserError):
            manager.add_path(bad)
    added = manager.add_path(str(second))
    assert added["state"] == "needs_index" and not added["default"]
    assert manager.add_path(str(second))["id"] == added["id"]  # no duplicates
    assert [p["name"] for p in ProjectManager(first, Runtime).projects()] == ["first", "second"]
    with pytest.raises(UserError):
        manager.remove(manager.default_id)
    manager.remove(added["id"])
    assert [p["name"] for p in manager.projects()] == ["first"]
    assert second.is_dir()  # removing never deletes files
    with pytest.raises(NotFoundError):
        manager.get(added["id"])


def test_indexing_a_project_is_explicit_and_creates_its_index(tmp_path: Path) -> None:
    first = make_repo(tmp_path, "small", "first")
    second = make_repo(tmp_path, "tiny", "second", index=False)
    manager = ProjectManager(first, Runtime)
    added = manager.add_path(str(second))
    assert not (second / ".aicontext").exists()  # adding alone changes nothing
    manager.index(added["id"])
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and manager.record(added["id"])["state"] != "ready":
        time.sleep(0.3)
    record = manager.record(added["id"])
    assert record["state"] == "ready" and record["files"] and (second / ".aicontext").is_dir()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "ext::sh -c id",
        "file:///etc",
        "git@github.com:a/b.git",
        "",
        "https://x/",
    ],
)
def test_git_urls_must_be_plain_https(tmp_path: Path, url: str) -> None:
    manager = ProjectManager(make_repo(tmp_path, "small", "first"), Runtime)
    with pytest.raises(UserError):
        manager.add_git(url)


def test_clone_reports_progress_before_destination_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    manager = ProjectManager(make_repo(tmp_path, "small", "first"), Runtime)
    release = threading.Event()
    finished = threading.Event()

    def delayed_clone(ident: str, url: str, destination: Path) -> None:
        try:
            assert release.wait(10)
            destination.mkdir()
            manager._finish(ident, None)
        finally:
            finished.set()

    monkeypatch.setattr(manager, "_clone_then_index", delayed_clone)
    try:
        added = manager.add_git("https://github.com/example/project.git")
        assert not Path(added["root"]).exists()
        assert added["state"] == "cloning"
        assert added["error"] is None
        assert manager.projects()[-1]["state"] == "cloning"
    finally:
        release.set()
        assert finished.wait(10)


def test_clone_failure_preserves_error_when_destination_is_absent(tmp_path: Path) -> None:
    manager = ProjectManager(make_repo(tmp_path, "small", "first"), Runtime)
    ident = manager._add_record(
        tmp_path / "download", source="git", url="https://github.com/example/project.git"
    )
    manager._finish(ident, "git clone failed: repository not found")
    record = manager.record(ident)
    assert record["state"] == "failed"
    assert record["error"] == "git clone failed: repository not found"


def test_http_routes_follow_the_selected_project(tmp_path: Path) -> None:
    first = make_repo(tmp_path, "small", "first")
    second = make_repo(tmp_path, "tiny", "second")
    server = ViewerServer(first)
    server.start()

    def request(
        path: str, method: str = "GET", data: dict[str, Any] | None = None, **headers: str
    ) -> tuple[int, bytes, str | None]:
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
        sent = {"Content-Type": "application/json", "X-Prism-Token": server.token, **headers}
        body = json.dumps(data) if data is not None else None
        conn.request(method, path, body=body, headers=sent)
        response = conn.getresponse()
        result = (response.status, response.read(), response.getheader("Set-Cookie"))
        conn.close()
        return result

    def project_of(**headers: str) -> str:
        return str(json.loads(request("/api/dashboard/status", **headers)[1])["project"])

    try:
        code, body, _ = request("/api/dashboard/projects", "POST", {"path": str(second)})
        assert code == 201
        other = json.loads(body)["id"]
        listing = json.loads(request("/api/dashboard/projects")[1])
        assert {p["name"] for p in listing["projects"]} == {"first", "second"}
        assert listing["selected"] == listing["default"]
        assert project_of() == "first"
        assert project_of(**{"X-Prism-Project": other}) == "second"
        code, _, cookie = request("/api/dashboard/projects/select", "POST", {"id": other})
        assert code == 200 and cookie and other in cookie
        assert project_of(Cookie=cookie.split(";")[0]) == "second"  # the graph iframe's choice
        assert request("/api/dashboard/status", **{"X-Prism-Project": "nope"})[0] == 404
        assert project_of(Cookie=f"prism_project_{server.port}=nope") == "first"  # stale cookie
        assert request("/api/dashboard/projects", "POST", {"path": "relative"})[0] == 400
        remove = "/api/dashboard/projects/remove"
        assert request(remove, "POST", {"id": listing["default"]})[0] == 400
        evil = {"Origin": "http://evil.example"}
        assert request("/api/dashboard/projects", "POST", {"path": str(second)}, **evil)[0] == 403
        assert request(remove, "POST", {"id": other})[0] == 200
    finally:
        server.shutdown()
