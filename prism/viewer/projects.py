"""Projects the dashboard can show side by side.

A project is a folder on this computer. It is added by typing its path, or by giving a git URL that is
cloned into PRISM's own folder. Adding a folder never changes it; indexing it (an explicit action) creates
`.aicontext/` inside it, exactly like `prism init`. The list survives restarts in the user config folder.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prism.consent.registry import config_home
from prism.core.errors import NotFoundError, UserError
from prism.writers.json_writer import write_json
from prism.writers.manifest import load_manifest

_GIT_URL = re.compile(r"^https://[A-Za-z0-9.-]+/[A-Za-z0-9._~/-]+$")
_BUSY = ("cloning", "indexing")


def _identify(root: Path) -> str:
    return hashlib.sha256(root.resolve().as_posix().encode()).hexdigest()[:12]


class ProjectManager:
    """Registry of projects plus a lazily created runtime object (backend, dashboard) for each."""

    def __init__(self, first_root: Path, factory: Callable[[Path], Any]) -> None:
        self._factory = factory
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._runtimes: dict[str, Any] = {}
        self._jobs: dict[str, dict[str, Any]] = {}
        self._path = config_home() / "dashboard-projects.json"
        self.default_id = _identify(first_root)
        self._add_record(first_root, source="path", url=None, persist=False)
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            for row in saved if isinstance(saved, list) else []:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("root"), str)
                    and Path(row["root"]).is_dir()
                ):
                    self._add_record(
                        Path(row["root"]),
                        source="git" if row.get("source") == "git" else "path",
                        url=row.get("url") if isinstance(row.get("url"), str) else None,
                        persist=False,
                    )
        except (OSError, ValueError):
            pass

    # --- records ------------------------------------------------------------------------

    def _add_record(self, root: Path, source: str, url: str | None, persist: bool = True) -> str:
        root = root.resolve()
        ident = _identify(root)
        with self._lock:
            self._records.setdefault(
                ident,
                {
                    "id": ident,
                    "name": root.name or str(root),
                    "root": str(root),
                    "source": source,
                    "url": url,
                },
            )
            if persist:
                self._save()
        return ident

    def _save(self) -> None:
        rows = [r for r in self._records.values() if r["id"] != self.default_id]
        write_json(self._path, rows)

    def _public(self, record: dict[str, Any]) -> dict[str, Any]:
        root = Path(record["root"])
        manifest = load_manifest(root) if root.is_dir() else None
        job = self._jobs.get(record["id"])
        if not root.is_dir():
            state, error = "missing", "The folder no longer exists"
        elif job and job["state"] in _BUSY:
            state, error = job["state"], None
        elif job and job["state"] == "failed":
            state, error = "failed", job.get("error")
        else:
            state, error = ("ready", None) if manifest else ("needs_index", None)
        stats = (manifest or {}).get("stats", {})
        return {
            **record,
            "state": state,
            "error": error,
            "default": record["id"] == self.default_id,
            "files": stats.get("files"),
            "symbols": stats.get("symbols"),
            "last_scan": (manifest or {}).get("last_scan"),
        }

    def projects(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(r) for r in self._records.values()]

    def record(self, ident: str | None) -> dict[str, Any]:
        with self._lock:
            key = ident or self.default_id
            if key not in self._records:
                raise NotFoundError("Unknown project")
            return self._public(self._records[key])

    def get(self, ident: str | None) -> Any:
        """The runtime for a project (the default when none is named)."""
        with self._lock:
            key = ident or self.default_id
            if key not in self._records:
                raise NotFoundError("Unknown project")
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = self._factory(Path(self._records[key]["root"]))
                self._runtimes[key] = runtime
            return runtime

    def runtimes(self) -> list[Any]:
        with self._lock:
            return list(self._runtimes.values())

    # --- adding, indexing, removing -------------------------------------------------------

    def add_path(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise UserError("Enter the full path of a project folder")
        path = Path(value.strip().strip('"')).expanduser()
        if not path.is_absolute():
            raise UserError("Use the full path of the folder, for example C:\\Users\\you\\project")
        path = path.resolve()
        if not path.is_dir():
            raise UserError("That folder does not exist on this computer")
        if len(path.parts) <= 1:
            raise UserError("Choose a project folder, not a whole drive")
        ident = self._add_record(path, source="path", url=None)
        return self.record(ident)

    def add_git(self, url: Any) -> dict[str, Any]:
        if not isinstance(url, str) or len(url) > 300 or not _GIT_URL.fullmatch(url.strip()):
            raise UserError(
                "Enter an https:// git URL, for example https://github.com/owner/repo.git"
            )
        url = url.strip()
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "project"
        destination = config_home() / "dashboard-projects" / uuid.uuid4().hex / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        ident = self._add_record(destination, source="git", url=url)
        self._start(ident, self._clone_then_index, url, destination)
        return self.record(ident)

    def index(self, ident: str) -> dict[str, Any]:
        self.record(ident)
        self._start(ident, self._index_only)
        return self.record(ident)

    def _start(self, ident: str, target: Callable[..., None], *args: Any) -> None:
        with self._lock:
            if self._jobs.get(ident, {}).get("state") in _BUSY:
                raise UserError("This project is already being prepared")
            self._jobs[ident] = {"state": "indexing" if target == self._index_only else "cloning"}
        threading.Thread(target=target, args=(ident, *args), daemon=True).start()

    def _finish(self, ident: str, error: str | None) -> None:
        with self._lock:
            self._jobs[ident] = {"state": "failed", "error": error} if error else {"state": "done"}

    def _clone_then_index(self, ident: str, url: str, destination: Path) -> None:
        try:
            process = subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.https.allow=always",
                    "clone",
                    "--depth",
                    "100",
                    url,
                    str(destination),
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if process.returncode:
                shutil.rmtree(destination, ignore_errors=True)
                self._finish(ident, f"git clone failed: {process.stderr.strip()[-300:]}")
                return
            with self._lock:
                self._jobs[ident] = {"state": "indexing"}
            self._index_work(destination)
            self._finish(ident, None)
        except Exception as exc:  # reported on the project card, never raised into the server
            self._finish(ident, str(exc)[:300])

    def _index_only(self, ident: str) -> None:
        try:
            self._index_work(Path(self._records[ident]["root"]))
            self._finish(ident, None)
        except Exception as exc:
            self._finish(ident, str(exc)[:300])

    @staticmethod
    def _index_work(root: Path) -> None:
        from prism.lifecycle import apply_init, plan_init, scan

        apply_init(plan_init(root))
        scan(root)

    def remove(self, ident: str) -> None:
        """Forget a project. Files are never deleted. The project the server started on stays."""
        with self._lock:
            record = self.record(ident)
            if record["default"]:
                raise UserError("The project this server was started on cannot be removed")
            runtime = self._runtimes.get(ident)
            if runtime is not None and runtime.dashboard.live.running():
                raise UserError("Stop the live comparison first")
            self._records.pop(ident, None)
            self._runtimes.pop(ident, None)
            self._jobs.pop(ident, None)
            self._save()
        if runtime is not None:
            runtime.close()
