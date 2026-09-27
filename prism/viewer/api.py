"""Viewer API: request parameters -> library calls -> JSON. Shared by the server and exports."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from prism.core.errors import NotFoundError, PrismError, UserError
from prism.core.paths import AICONTEXT
from prism.navigator import api as nav
from prism.navigator.store import IndexStore
from prism.viewer.model import LEVELS, GraphFilters, GraphModel
from prism.writers.json_writer import read_json, write_json
from prism.writers.manifest import load_manifest

MAX_LAYOUT_NODES = 50_000
_VIEW_NAME = re.compile(r"^[A-Za-z0-9 _.-]{1,64}$")


class ViewerBackend:
    """Holds the graph model and index store, reloading both when the index changes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = threading.Lock()
        self._model: GraphModel | None = None
        self._store: IndexStore | None = None

    def model(self) -> GraphModel:
        with self._lock:
            manifest = load_manifest(self.root) or {}
            fp = json.dumps(manifest.get("artifacts", {}), sort_keys=True)
            if self._model is None or self._model.fingerprint != fp:
                self._model = GraphModel(self.root)
            return self._model

    def store(self) -> IndexStore:
        with self._lock:
            if self._store is None or not self._store.is_current():
                if self._store is not None:
                    self._store.close()
                self._store = IndexStore.open(self.root)
            return self._store

    # --- endpoints ----------------------------------------------------------------

    def graph(self, q: dict[str, str]) -> dict[str, Any]:
        level = q.get("level", "file")
        if level not in LEVELS:
            raise UserError(f"level must be one of {', '.join(LEVELS)}")
        depth = max(1, min(4, int(q.get("depth", 2) or 2)))
        cap = max(10, min(20_000, int(q.get("cap", 5000) or 5000)))
        payload = self.model().graph(
            layer=q.get("layer", "import"),
            level=level,
            root=q.get("root") or None,
            depth=depth,
            filters=GraphFilters.from_query(q),
            node_cap=cap,
        )
        return payload.to_dict()

    def node(self, node_id: str) -> dict[str, Any]:
        model = self.model()
        if node_id.startswith("pkg:"):
            group = node_id[4:]
            files = sorted(
                m["file"] for mid, m in model.modules.items() if model.group_of_module[mid] == group
            )
            if not files:
                raise NotFoundError(f"no package '{group}'")
            try:
                summary = nav.op_module(self.store(), group)["text"]
            except PrismError:
                summary = ""
            return {
                "id": node_id,
                "kind": "cluster",
                "group": group,
                "files": files,
                "summary": summary,
            }
        if node_id.startswith("route:"):
            method, _, path = node_id[6:].partition(" ")
            route = next(
                (r for r in model.routes if r["method"] == method and r["path"] == path), None
            )
            if route is None:
                raise NotFoundError(f"no route '{node_id[6:]}'")
            return {
                "id": node_id,
                "kind": "route",
                **route,
                "editor": self._editor(route["file"], route["line"]),
            }
        pack = nav.op_context(self.store(), node_id)
        target = pack["target"]
        file = target["file"]
        start = (target.get("lines") or [1, 1])[0]
        extra: dict[str, Any] = {}
        health = model.health_files.get(file, {})
        if health:
            extra["owners"] = health.get("owners", [])
            extra["churn"] = health.get("churn", 0)
            extra["smells"] = [
                s for s in health.get("smells", []) if s.get("symbol") in (None, target["id"])
            ][:20]
        extra["findings"] = [
            f
            for f in self.store().findings()
            if f.get("status") == "open"
            and (f.get("symbol") == target["id"] or f.get("file") == file)
        ]
        extra["dead"] = target["id"] in model.dead
        return {
            "id": node_id,
            "pack": pack,
            "editor": self._editor(file, start),
            "context_command": f"prism context {target['id']}",
            **extra,
        }

    def _editor(self, file: str, line: int) -> dict[str, Any]:
        return {"path": (self.root / file).as_posix(), "line": line}

    def search(self, q: dict[str, str]) -> dict[str, Any]:
        query = q.get("q", "")
        data = nav.op_search(self.store(), query, int(q.get("limit", 15) or 15))
        level = q.get("level", "file")
        model = self.model()
        for hit in data["hits"]:
            hit["node"] = (
                model.node_id_at(level, hit["id"])
                if hit["kind"] != "route"
                else f"route:{hit['id']}"
            )
        return data

    def path(self, q: dict[str, str]) -> dict[str, Any]:
        if not q.get("from") or not q.get("to"):
            raise UserError("path needs `from` and `to`")
        return self.model().path(
            q["from"], q["to"], q.get("layer", "import"), q.get("level", "file")
        )

    def impact(self, target: str, q: dict[str, str]) -> dict[str, Any]:
        data = nav.op_impact(self.store(), target, int(q.get("depth", 3) or 3))
        level = q.get("level", "file")
        model = self.model()
        rings: dict[str, int] = {}
        for ring in data["dependents"]:
            for ref in [*ring["symbols"], *ring["files"]]:
                node = model.node_id_at(level, ref)
                if node is not None:
                    rings[node] = min(ring["distance"], rings.get(node, 99))
        data["rings"] = rings
        return data

    def diff(self, q: dict[str, str]) -> dict[str, Any]:
        since = q.get("since")
        if not since:
            raise UserError("diff needs `since` (a git ref, or `drift`)")
        return self.model().diff(since)

    def meta(self) -> dict[str, Any]:
        manifest = load_manifest(self.root) or {}
        model = self.model()
        return {
            "project": self.root.name,
            "stats": manifest.get("stats", {}),
            "last_scan": manifest.get("last_scan"),
            "levels": list(LEVELS),
            "layers": ["import", "call", "tests", "cochange", "routes"],
            "git": bool(model.last_changed),
            "has_routes": bool(model.routes),
            "static": False,
        }

    # --- layout and saved views (cache only; never source files) -------------------

    def _cache(self) -> Path:
        return self.root / AICONTEXT / "cache"

    def get_layout(self) -> dict[str, Any]:
        path = self._cache() / "layout.json"
        data = read_json(path) if path.is_file() else {}
        return data if isinstance(data, dict) else {}

    def save_layout(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("positions"), dict):
            raise UserError('layout body must be {"positions": {id: [x, y]}}')
        current = self.get_layout().get("positions", {})
        for key, value in body["positions"].items():
            if (
                isinstance(key, str)
                and isinstance(value, list)
                and len(value) == 2
                and all(isinstance(v, (int, float)) for v in value)
            ):
                current[key] = [round(float(value[0]), 2), round(float(value[1]), 2)]
        if len(current) > MAX_LAYOUT_NODES:
            current = dict(list(current.items())[-MAX_LAYOUT_NODES:])
        write_json(self._cache() / "layout.json", {"positions": current})
        return {"saved": len(current)}

    def list_views(self) -> dict[str, Any]:
        directory = self._cache() / "views"
        views = {}
        if directory.is_dir():
            for p in sorted(directory.glob("*.json")):
                try:
                    views[p.stem] = read_json(p)
                except ValueError:
                    continue
        return {"views": views}

    def save_view(self, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("name"), str)
            or not _VIEW_NAME.match(body["name"])
        ):
            raise UserError("a view needs a `name` (letters, digits, space, _ . -)")
        state = body.get("state")
        if not isinstance(state, dict) or len(json.dumps(state)) > 200_000:
            raise UserError("view `state` must be an object under 200 KB")
        write_json(self._cache() / "views" / f"{body['name']}.json", state)
        return {"saved": body["name"]}
