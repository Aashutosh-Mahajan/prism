"""Graph model behind the viewer API and the graph exporters.

Loads the `.aicontext/` artifacts once (per index fingerprint) and serves
node/edge sets at three levels of detail (package, file, symbol) for five
layers (import, call, tests, cochange, routes). The viewer never parses code.
"""

from __future__ import annotations

import fnmatch
import itertools
import json
import math
import subprocess
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prism.core.errors import IndexMissingError, NotFoundError, UserError
from prism.core.paths import AICONTEXT
from prism.writers.manifest import load_manifest

LEVELS = ("package", "file", "symbol")
LAYERS = ("import", "call", "tests", "cochange", "routes")
DEFAULT_NODE_CAP = 5000


@dataclass
class GraphFilters:
    path: str | None = None  # glob on file path, e.g. "src/shop/pricing/*"
    kinds: set[str] | None = None
    hide_tests: bool = False
    orphans_only: bool = False
    min_rank: float = 0.0  # 0..1, relative to the highest rank at this level
    min_risk: float = 0.0
    changed_since: str | None = None  # git ref

    @classmethod
    def from_query(cls, q: dict[str, str]) -> GraphFilters:
        kinds = {k for k in q.get("kinds", "").split(",") if k} or None
        try:
            rank = float(q.get("min_rank", 0) or 0)
            risk = float(q.get("min_risk", 0) or 0)
        except ValueError as exc:
            raise UserError("min_rank and min_risk must be numbers between 0 and 1") from exc
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (rank, risk)):
            raise UserError("min_rank and min_risk must be numbers between 0 and 1")
        return cls(
            path=q.get("path") or None,
            kinds=kinds,
            hide_tests=q.get("hide_tests") in ("1", "true"),
            orphans_only=q.get("orphans_only") in ("1", "true"),
            min_rank=rank,
            min_risk=risk,
            changed_since=q.get("changed_since") or None,
        )


@dataclass
class GraphPayload:
    level: str
    layer: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: int = 0
    root: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "layer": self.layer,
            "root": self.root,
            "nodes": self.nodes,
            "edges": self.edges,
            "truncated": self.truncated,
            "counts": {"nodes": len(self.nodes), "edges": len(self.edges)},
        }


def _read(out: Path, name: str) -> dict[str, Any]:
    path = out / name
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _group_of(module: str, is_package: bool, packages: set[str]) -> str:
    if is_package:
        return module
    parent = module.rsplit(".", 1)[0] if "." in module else ""
    return parent if parent in packages else module


def git_changes(root: Path, ref: str) -> dict[str, str]:
    """path -> status letter (A/M/D/R...) for changes between `ref` and the working tree."""
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", "diff", "--name-status", "--relative", ref],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UserError(f"git is not available: {exc}") from exc
    if out.returncode != 0:
        raise UserError(f"cannot diff against '{ref}': {out.stderr.strip()[:200]}")
    changes: dict[str, str] = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changes[parts[-1]] = parts[0][0]
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    for line in untracked.stdout.splitlines():
        if line.strip():
            changes.setdefault(line.strip(), "A")
    return changes


class GraphModel:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        manifest = load_manifest(self.root)
        if manifest is None or not manifest.get("last_scan"):
            raise IndexMissingError("no index; run `prism scan` first")
        self.fingerprint = json.dumps(manifest.get("artifacts", {}), sort_keys=True)
        out = self.root / AICONTEXT
        symbols = _read(out, "symbols.json").get("symbols", [])
        dep = _read(out, "dependency_graph.json")
        calls = _read(out, "call_graph.json").get("edges", [])
        tests = _read(out, "tests_map.json")
        health = _read(out, "health.json")
        git = _read(out, "git_intelligence.json")
        blast = _read(out, "blast_radius.json")
        self.routes = _read(out, "routes.json").get("routes", [])
        self.models = {m["id"]: m for m in _read(out, "models.json").get("models", [])}
        findings = _read(out / "audit", "findings.json").get("findings", [])

        self.test_files: set[str] = set(tests.get("test_files", []))
        self.modules: dict[str, dict[str, Any]] = {m["id"]: m for m in dep.get("modules", [])}
        self.module_by_file = {m["file"]: m for m in self.modules.values()}
        packages = {m["id"] for m in self.modules.values() if m["is_package"]}
        self.group_of_module = {
            mid: _group_of(mid, m["is_package"], packages) for mid, m in self.modules.items()
        }
        self.symbols: dict[str, dict[str, Any]] = {s["id"]: s for s in symbols}
        self.import_edges: list[tuple[str, str]] = [
            (e["from"], e["to"]) for e in dep.get("edges", [])
        ]
        self.call_edges: list[tuple[str, str, str]] = [
            (e["from"], e["to"], e["confidence"]) for e in calls
        ]
        self.tests_by_file: dict[str, list[str]] = tests.get("by_file", {})
        self.cochange = [(p["a"], p["b"], p["strength"]) for p in git.get("co_change", [])]
        self.health_files: dict[str, Any] = health.get("files", {})
        self.health_symbols: dict[str, Any] = health.get("symbols", {})
        self.dead: set[str] = {d["id"] for d in health.get("dead_code", [])}
        self.last_changed: dict[str, int] = git.get("last_changed", {})
        self.blast_files: dict[str, Any] = blast.get("files", {})
        self.blast_symbols: dict[str, Any] = blast.get("symbols", {})
        self.findings_by_key: dict[str, int] = {}
        for f in findings:
            if f.get("status") == "open":
                for key in (f.get("file"), f.get("symbol")):
                    if key:
                        self.findings_by_key[key] = self.findings_by_key.get(key, 0) + 1
        self._node_cache: dict[str, list[dict[str, Any]]] = {}
        self._edge_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.language_of = {
            path: e.get("language") for path, e in manifest.get("files", {}).items()
        }

    # --- node construction ------------------------------------------------------

    def _file_node(self, m: dict[str, Any]) -> dict[str, Any]:
        path = m["file"]
        h = self.health_files.get(path, {})
        is_test = path in self.test_files
        return {
            "id": path,
            "label": m["id"].rsplit(".", 1)[-1]
            if not m["is_package"]
            else m["id"].rsplit(".", 1)[-1] + "/",
            "kind": "test" if is_test else ("package" if m["is_package"] else "module"),
            "module": m["id"],
            "file": path,
            "group": self.group_of_module.get(m["id"], m["id"]),
            "rank": m["rank"],
            "loc": m.get("loc", 0),
            "blast": self.blast_files.get(path, {}).get("count", 0),
            "risk": h.get("risk", 0.0),
            "owner": (h.get("owners") or [None])[0],
            "language": self.language_of.get(path) or "python",
            "last_changed": self.last_changed.get(path),
            "findings": self.findings_by_key.get(path, 0),
            "test": is_test,
            "entry_point": m.get("entry_point"),
            "community": m.get("community", 0),
            "doc": m.get("doc", ""),
        }

    def _symbol_node(self, s: dict[str, Any]) -> dict[str, Any]:
        path = s["file"]
        is_test = path in self.test_files
        m = self.module_by_file.get(path, {})
        fh = self.health_files.get(path, {})
        return {
            "id": s["id"],
            "label": s["id"].rsplit(".", 1)[-1],
            "kind": "test" if is_test else s["kind"],
            "module": s["module"],
            "file": path,
            "lines": s["lines"],
            "group": self.group_of_module.get(m.get("id", s["module"]), s["module"]),
            "rank": s["rank"],
            "loc": s["lines"][1] - s["lines"][0] + 1,
            "blast": self.blast_symbols.get(s["id"], {}).get("count", 0),
            "risk": self.health_symbols.get(s["id"], {}).get("risk", fh.get("risk", 0.0)),
            "owner": (fh.get("owners") or [None])[0],
            "language": "python",
            "last_changed": self.last_changed.get(path),
            "findings": self.findings_by_key.get(s["id"], 0),
            "test": is_test,
            "dead": s["id"] in self.dead,
            "signature": s["signature"],
            "doc": s["doc"],
            "model": s["id"] in self.models,
            "community": m.get("community", 0),
        }

    def _package_nodes(self, file_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for n in file_nodes:
            gid = n["group"]
            g = groups.setdefault(
                gid,
                {
                    "id": f"pkg:{gid}",
                    "label": gid,
                    "kind": "cluster",
                    "group": gid,
                    "rank": 0.0,
                    "loc": 0,
                    "blast": 0,
                    "risk": 0.0,
                    "findings": 0,
                    "test": True,
                    "files": 0,
                    "owner": None,
                    "language": n["language"],
                    "last_changed": None,
                    "file": None,
                    "module": gid,
                },
            )
            if g["files"] == 0 or n["kind"] == "package":
                g["dir"] = n["file"].rsplit("/", 1)[0] if n["kind"] == "package" else n["file"]
            g["rank"] += n["rank"]
            g["loc"] += n["loc"]
            g["blast"] = max(g["blast"], n["blast"])
            g["risk"] = max(g["risk"], n["risk"])
            g["findings"] += n["findings"]
            g["test"] = g["test"] and n["test"]
            g["files"] += 1
            if n["last_changed"]:
                g["last_changed"] = max(g["last_changed"] or 0, n["last_changed"])
        for g in groups.values():
            g["rank"] = round(g["rank"], 6)
        return sorted(groups.values(), key=lambda g: g["id"])

    def canonical(self, ref: str) -> str:
        """Resolve a short reference (`apply_discount`, `cart.py`) to a unique full id, if one exists."""
        if (
            ref in self.symbols
            or ref in self.modules
            or ref in self.module_by_file
            or ref.startswith(("pkg:", "route:"))
        ):
            return ref
        for pool, sep in ((self.symbols, "."), (self.modules, "."), (self.module_by_file, "/")):
            hits: list[str] = [str(k) for k in pool if k.endswith(sep + ref)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise UserError(f"'{ref}' is ambiguous: " + ", ".join(sorted(hits)[:5]))
        return ref

    def node_id_at(self, level: str, ref: str) -> str | None:
        """Map any reference (symbol id, module id, file path, pkg:...) to a node id at `level`."""
        ref = self.canonical(ref)
        file = None
        if ref in self.symbols:
            if level == "symbol":
                return ref
            file = self.symbols[ref]["file"]
        elif ref in self.modules:
            file = self.modules[ref]["file"]
        elif ref in self.module_by_file:
            file = ref
        elif ref.startswith("pkg:"):
            return ref if level == "package" else None
        if file is None:
            return None
        if level == "file":
            return str(file)
        if level == "package":
            m = self.module_by_file[file]
            return f"pkg:{self.group_of_module[m['id']]}"
        # symbol level from a file: its highest-ranked top-level symbol
        syms = [s for s in self.symbols.values() if s["file"] == file and s["parent"] is None]
        return max(syms, key=lambda s: (s["rank"], s["id"]))["id"] if syms else None

    # --- edges ------------------------------------------------------------------

    def _raw_edges(self, layer: str, level: str) -> list[dict[str, Any]]:
        """Edges at a level, cached per model, with import cycles already flagged."""
        key = (layer, level)
        cached = self._edge_cache.get(key)
        if cached is None:
            cached = self._build_edges(layer, level)
            if layer == "import":
                cyclic = self.cycle_edges(cached)
                cached = [{**e, "cycle": True} if e["id"] in cyclic else e for e in cached]
            self._edge_cache[key] = cached
        return cached

    def _build_edges(self, layer: str, level: str) -> list[dict[str, Any]]:
        """Edges at the requested level (aggregated for coarser levels)."""
        file_of_module = {mid: m["file"] for mid, m in self.modules.items()}
        base: list[tuple[str, str, float, str]] = []  # file-level (or symbol-level) edges
        if layer == "import":
            base = [
                (file_of_module[a], file_of_module[b], 1.0, "high") for a, b in self.import_edges
            ]
            src_level = "file"
        elif layer == "call":
            base = [(a, b, 1.0, c) for a, b, c in self.call_edges]
            src_level = "symbol"
        elif layer == "tests":
            if level == "symbol":
                base = [
                    (a, b, 1.0, c)
                    for a, b, c in self.call_edges
                    if self.symbols[a]["file"] in self.test_files
                    and self.symbols[b]["file"] not in self.test_files
                ]
                src_level = "symbol"
            else:
                base = [(t, f, 1.0, "high") for f, ts in self.tests_by_file.items() for t in ts]
                src_level = "file"
        elif layer == "cochange":
            base = [(a, b, s, "high") for a, b, s in self.cochange]
            src_level = "file"
        else:
            raise UserError(f"layer must be one of {', '.join(LAYERS)}")

        def lift(node: str) -> str | None:
            if src_level == "symbol":
                return self.node_id_at(level, node) if level != "symbol" else node
            return self.node_id_at(level, node) if level != "file" else node

        if level == "symbol" and src_level == "file":
            return []  # file-level relations have no symbol-level meaning
        agg: dict[tuple[str, str], dict[str, Any]] = {}
        for a, b, w, conf in base:
            la, lb = lift(a), lift(b)
            if la is None or lb is None or la == lb:
                continue
            key = (la, lb)
            e = agg.get(key)
            if e is None:
                agg[key] = {
                    "source": la,
                    "target": lb,
                    "weight": w,
                    "confidence": conf,
                    "layer": layer,
                }
            else:
                e["weight"] += w
                if conf == "high":
                    e["confidence"] = "high"
        edges = sorted(agg.values(), key=lambda e: (e["source"], e["target"]))
        for e in edges:
            e["id"] = f"{e['source']}->{e['target']}"
            e["weight"] = round(e["weight"], 3)
        return edges

    def _route_graph(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        called: dict[str, list[str]] = {}
        for a, b, _ in self.call_edges:
            called.setdefault(a, []).append(b)
        for r in self.routes:
            rid = f"route:{r['method']} {r['path']}"
            nodes[rid] = {
                "id": rid,
                "label": f"{r['method']} {r['path']}",
                "kind": "route",
                "file": r["file"],
                "group": "routes",
                "rank": 0.0,
                "loc": 1,
                "blast": 0,
                "risk": 0.0,
                "findings": 0,
                "test": False,
                "language": "python",
                "owner": None,
                "last_changed": None,
            }
            handler = self.symbols.get(r["handler"])
            if handler is None:
                continue
            nodes[handler["id"]] = self._symbol_node(handler)
            edges.append(
                {
                    "source": rid,
                    "target": handler["id"],
                    "layer": "routes",
                    "weight": 1,
                    "confidence": "high",
                }
            )
            for callee in called.get(handler["id"], []):
                if callee in self.models:
                    nodes[callee] = self._symbol_node(self.symbols[callee])
                    edges.append(
                        {
                            "source": handler["id"],
                            "target": callee,
                            "layer": "routes",
                            "weight": 1,
                            "confidence": "high",
                        }
                    )
        for e in edges:
            e["id"] = f"{e['source']}->{e['target']}"
        return sorted(nodes.values(), key=lambda n: n["id"]), edges

    # --- public API -----------------------------------------------------------------

    def nodes_at(self, level: str) -> list[dict[str, Any]]:
        """Nodes at a level. Cached per model (the model is immutable per index version);
        callers must copy a node before changing it."""
        if level not in LEVELS:
            raise UserError(f"level must be one of {', '.join(LEVELS)}")
        cached = self._node_cache.get(level)
        if cached is None:
            cached = self._node_cache[level] = self._build_nodes(level)
        return cached

    def _build_nodes(self, level: str) -> list[dict[str, Any]]:
        if level == "symbol":
            return [self._symbol_node(s) for _, s in sorted(self.symbols.items())]
        file_nodes = [
            self._file_node(m) for m in sorted(self.modules.values(), key=lambda m: m["file"])
        ]
        if level == "file":
            return file_nodes
        if level == "package":
            return self._package_nodes(file_nodes)
        raise AssertionError("unreachable graph level")

    def graph(
        self,
        layer: str = "import",
        level: str = "file",
        root: str | None = None,
        depth: int = 2,
        filters: GraphFilters | None = None,
        node_cap: int = DEFAULT_NODE_CAP,
    ) -> GraphPayload:
        filters = filters or GraphFilters()
        if layer == "routes":
            nodes, edges = self._route_graph()
            level = "symbol"
        else:
            if layer == "call" and level not in LEVELS:
                raise UserError(f"level must be one of {', '.join(LEVELS)}")
            nodes = self.nodes_at(level)
            edges = self._raw_edges(layer, level)

        changed: dict[str, str] | None = (
            git_changes(self.root, filters.changed_since) if filters.changed_since else None
        )
        max_rank = max((n["rank"] for n in nodes), default=0.0) or 1.0
        # A package cluster matches a path glob if any of its files does.
        matched_groups: set[str] = set()
        if filters.path and level == "package":
            matched_groups = {
                self.group_of_module[m["id"]]
                for m in self.modules.values()
                if fnmatch.fnmatch(m["file"], filters.path)
            }
        keep: dict[str, dict[str, Any]] = {}
        for n in nodes:
            if filters.hide_tests and n.get("test"):
                continue
            if filters.kinds and n["kind"] not in filters.kinds:
                continue
            if filters.path:
                if n["kind"] == "cluster":
                    if n["group"] not in matched_groups:
                        continue
                elif not (n.get("file") and fnmatch.fnmatch(n["file"], filters.path)):
                    continue
            if n["rank"] / max_rank < filters.min_rank or n["risk"] < filters.min_risk:
                continue
            if changed is not None:
                if n["kind"] == "cluster" or not n.get("file") or n["file"] not in changed:
                    continue
                n = {**n, "change": changed[n["file"]]}
            keep[n["id"]] = n
        edges = [e for e in edges if e["source"] in keep and e["target"] in keep]

        root_id = None
        if root:
            root_id = (
                self.node_id_at(level, root)
                if layer != "routes"
                else (root if root in keep else None)
            )
            if root_id is None or root_id not in keep:
                raise NotFoundError(f"'{root}' is not in the {level}-level {layer} graph")
            near = self._neighborhood(root_id, edges, depth)
            keep = {k: {**v, "distance": near[k]} for k, v in keep.items() if k in near}
            edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
        if filters.orphans_only:
            linked = {e["source"] for e in edges} | {e["target"] for e in edges}
            keep = {k: v for k, v in keep.items() if k not in linked}
            edges = []

        degree_in: dict[str, int] = {}
        degree_out: dict[str, int] = {}
        for e in edges:
            degree_out[e["source"]] = degree_out.get(e["source"], 0) + 1
            degree_in[e["target"]] = degree_in.get(e["target"], 0) + 1
        ordered = sorted(keep.values(), key=lambda n: (-n["rank"], n["id"]))
        truncated = max(0, len(ordered) - node_cap)
        if truncated:
            if root_id:
                ordered.sort(key=lambda n: (n.get("distance", 0), -n["rank"], n["id"]))
            ordered = ordered[:node_cap]
            ids = {n["id"] for n in ordered}
            edges = [e for e in edges if e["source"] in ids and e["target"] in ids]
        # Copies: cached nodes are shared between requests and must not change.
        ordered = [
            {**n, "fan_in": degree_in.get(n["id"], 0), "fan_out": degree_out.get(n["id"], 0)}
            for n in ordered
        ]
        ordered.sort(key=lambda n: n["id"])
        return GraphPayload(level, layer, ordered, edges, truncated, root_id)

    @staticmethod
    def _neighborhood(root: str, edges: list[dict[str, Any]], depth: int) -> dict[str, int]:
        adj: dict[str, set[str]] = {}
        for e in edges:
            adj.setdefault(e["source"], set()).add(e["target"])
            adj.setdefault(e["target"], set()).add(e["source"])
        dist = {root: 0}
        queue = deque([root])
        while queue:
            cur = queue.popleft()
            if dist[cur] >= depth:
                continue
            for nxt in sorted(adj.get(cur, ())):
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    queue.append(nxt)
        return dist

    @staticmethod
    def cycle_edges(edges: list[dict[str, Any]]) -> set[str]:
        """Edge ids inside a strongly connected component of size > 1 (Tarjan, iterative)."""
        adj: dict[str, list[str]] = {}
        for e in edges:
            adj.setdefault(e["source"], []).append(e["target"])
            adj.setdefault(e["target"], [])
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        comp: dict[str, int] = {}
        counter = 0
        n_comp = 0
        for start in sorted(adj):
            if start in index:
                continue
            work = [(start, 0)]
            while work:
                node, i = work.pop()
                if i == 0:
                    index[node] = low[node] = counter
                    counter += 1
                    stack.append(node)
                    on_stack.add(node)
                recurse = False
                succ = adj[node]
                while i < len(succ):
                    nxt = succ[i]
                    i += 1
                    if nxt not in index:
                        work.append((node, i))
                        work.append((nxt, 0))
                        recurse = True
                        break
                    if nxt in on_stack:
                        low[node] = min(low[node], index[nxt])
                if recurse:
                    continue
                if low[node] == index[node]:
                    members = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        members.append(w)
                        if w == node:
                            break
                    for w in members:
                        comp[w] = n_comp if len(members) > 1 else -1
                    n_comp += 1
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
        return {
            e["id"]
            for e in edges
            if comp.get(e["source"], -1) >= 0 and comp.get(e["source"]) == comp.get(e["target"])
        }

    def path(
        self, source: str, target: str, layer: str = "import", level: str = "file"
    ) -> dict[str, Any]:
        a, b = self.node_id_at(level, source), self.node_id_at(level, target)
        if a is None or b is None:
            raise NotFoundError(
                f"cannot place '{source if a is None else target}' in the {level} graph"
            )
        edges = self._raw_edges(layer, level)
        for directed in (True, False):
            adj: dict[str, list[str]] = {}
            for e in edges:
                adj.setdefault(e["source"], []).append(e["target"])
                if not directed:
                    adj.setdefault(e["target"], []).append(e["source"])
            prev: dict[str, str | None] = {a: None}
            queue = deque([a])
            while queue:
                cur = queue.popleft()
                if cur == b:
                    break
                for nxt in sorted(adj.get(cur, [])):
                    if nxt not in prev:
                        prev[nxt] = cur
                        queue.append(nxt)
            if b in prev:
                path = [b]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])  # type: ignore[arg-type]
                path.reverse()
                return {
                    "from": a,
                    "to": b,
                    "directed": directed,
                    "nodes": path,
                    "edges": [
                        f"{x}->{y}" if directed else f"{x}-{y}" for x, y in itertools.pairwise(path)
                    ],
                }
        return {"from": a, "to": b, "directed": True, "nodes": [], "edges": []}

    def diff(self, since: str) -> dict[str, Any]:
        if since == "drift":
            manifest = load_manifest(self.root) or {}
            ids = sorted(
                {
                    i
                    for s in manifest.get("drift", {}).get("sections", {}).values()
                    for i in s.get("ids", [])
                }
            )
            return {"since": since, "changed_ids": ids, "files": {}}
        changes = git_changes(self.root, since)
        indexed = {
            path: status
            for path, status in changes.items()
            if path in self.module_by_file or status == "D"
        }
        symbols = sorted(s for s, info in self.symbols.items() if info["file"] in indexed)
        return {"since": since, "files": dict(sorted(indexed.items())), "changed_ids": symbols}
