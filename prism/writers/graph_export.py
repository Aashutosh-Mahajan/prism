"""`prism graph export`: self-contained HTML, Mermaid, DOT, GraphML, and JSON.

All exports are deterministic and offline. The HTML export inlines the
viewer bundle and the graph data, so it opens from disk with no server and
no network access.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from prism.core.errors import UserError
from prism.viewer.model import GraphModel, GraphPayload
from prism.writers.json_writer import write_text

VIEWER_DIST = Path(__file__).resolve().parent.parent / "viewer_dist"
DIAGRAM_CAP = 150


def _payload(
    model: GraphModel, level: str, layer: str, around: str | None, depth: int, cap: int
) -> GraphPayload:
    return model.graph(layer=layer, level=level, root=around, depth=depth, node_cap=cap)


# --- text diagrams -----------------------------------------------------------------------------


def _mermaid_id(i: int) -> str:
    return f"n{i}"


def to_mermaid(p: GraphPayload) -> str:
    ids = {n["id"]: _mermaid_id(i) for i, n in enumerate(p.nodes)}
    lines = ["graph LR"]
    for n in p.nodes:
        label = n["label"].replace('"', "'")
        shape = ('["', '"]') if n["kind"] in ("module", "package", "cluster") else ('("', '")')
        lines.append(f"  {ids[n['id']]}{shape[0]}{label}{shape[1]}")
    for e in p.edges:
        arrow = "-.->" if e.get("confidence") == "low" else "-->"
        lines.append(f"  {ids[e['source']]} {arrow} {ids[e['target']]}")
    if p.root and p.root in ids:
        lines.append(f"  style {ids[p.root]} stroke-width:3px")
    return "\n".join(lines) + "\n"


def _dot_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_dot(p: GraphPayload) -> str:
    lines = ["digraph prism {", "  rankdir=LR;", '  node [fontname="Helvetica", fontsize=10];']
    for n in p.nodes:
        shape = "box" if n["kind"] in ("module", "package", "cluster") else "ellipse"
        attrs = f"label={_dot_quote(n['label'])}, shape={shape}"
        if n["id"] == p.root:
            attrs += ", penwidth=3"
        lines.append(f"  {_dot_quote(n['id'])} [{attrs}];")
    for e in p.edges:
        style = ', style="dashed"' if e.get("confidence") == "low" else ""
        color = ', color="red"' if e.get("cycle") else ""
        lines.append(
            f"  {_dot_quote(e['source'])} -> {_dot_quote(e['target'])} [weight={e['weight']}{style}{color}];"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


GRAPHML_KEYS = (
    ("label", "string"),
    ("kind", "string"),
    ("file", "string"),
    ("group", "string"),
    ("rank", "double"),
    ("risk", "double"),
    ("loc", "int"),
)


def to_graphml(p: GraphPayload) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for key, typ in GRAPHML_KEYS:
        out.append(f'  <key id="{key}" for="node" attr.name="{key}" attr.type="{typ}"/>')
    out.append('  <key id="weight" for="edge" attr.name="weight" attr.type="double"/>')
    out.append('  <key id="confidence" for="edge" attr.name="confidence" attr.type="string"/>')
    out.append('  <graph id="prism" edgedefault="directed">')
    for n in p.nodes:
        out.append(f'    <node id="{xml_escape(n["id"], {chr(34): "&quot;"})}">')
        for key, _ in GRAPHML_KEYS:
            value = n.get(key)
            if value is not None:
                out.append(f'      <data key="{key}">{xml_escape(str(value))}</data>')
        out.append("    </node>")
    for i, e in enumerate(p.edges):
        src = xml_escape(e["source"], {chr(34): "&quot;"})
        dst = xml_escape(e["target"], {chr(34): "&quot;"})
        out.append(f'    <edge id="e{i}" source="{src}" target="{dst}">')
        out.append(f'      <data key="weight">{e["weight"]}</data>')
        out.append(f'      <data key="confidence">{e.get("confidence", "high")}</data>')
        out.append("    </edge>")
    out += ["  </graph>", "</graphml>"]
    return "\n".join(out) + "\n"


def export_diagram(
    root: Path,
    fmt: str,
    out: Path | None,
    level: str = "file",
    layer: str = "import",
    around: str | None = None,
    depth: int = 1,
) -> str:
    model = GraphModel(root)
    cap = 100_000 if fmt in ("graphml", "json") or around else DIAGRAM_CAP
    p = _payload(model, level, layer, around, depth, cap)
    if fmt == "mermaid":
        text = to_mermaid(p)
    elif fmt == "dot":
        text = to_dot(p)
    elif fmt == "graphml":
        text = to_graphml(p)
    elif fmt == "json":
        text = json.dumps(p.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    else:
        raise UserError(f"unknown format '{fmt}'")
    if p.truncated and fmt in ("mermaid", "dot"):
        note = f"{p.truncated} lower-importance nodes omitted (cap {DIAGRAM_CAP}); use --around <target> to focus"
        text = (f"%% {note}\n" if fmt == "mermaid" else f"// {note}\n") + text
    if out is not None:
        write_text(out, text)
    return text


# --- self-contained HTML ---------------------------------------------------------------------


def _static_details(model: GraphModel, payloads: list[GraphPayload]) -> dict[str, Any]:
    callers: dict[str, list[str]] = {}
    callees: dict[str, list[str]] = {}
    for a, b, _ in model.call_edges:
        callees.setdefault(a, []).append(b)
        callers.setdefault(b, []).append(a)
    importers: dict[str, list[str]] = {}
    imports: dict[str, list[str]] = {}
    for a, b in model.import_edges:
        imports.setdefault(a, []).append(b)
        importers.setdefault(b, []).append(a)
    details: dict[str, Any] = {}
    wanted = {n["id"]: n for p in payloads for n in p.nodes}
    for node_id, n in sorted(wanted.items()):
        if n["kind"] == "cluster":
            files = sorted(
                m["file"]
                for mid, m in model.modules.items()
                if model.group_of_module[mid] == n["group"]
            )
            details[node_id] = {
                "id": node_id,
                "kind": "cluster",
                "group": n["group"],
                "files": files,
                "summary": "",
            }
            continue
        if node_id in model.symbols:
            s = model.symbols[node_id]
            h = model.health_symbols.get(node_id, {})
            pack = {
                "target": {
                    "id": node_id,
                    "kind": s["kind"],
                    "file": s["file"],
                    "lines": s["lines"],
                    "signature": s["signature"],
                },
                "summary": s["doc"],
                "callers": [
                    {
                        "id": c,
                        "file": model.symbols[c]["file"],
                        "line": model.symbols[c]["lines"][0],
                    }
                    for c in sorted(callers.get(node_id, []))[:15]
                ],
                "callees": [
                    {"id": c, "file": model.symbols[c]["file"]}
                    for c in sorted(callees.get(node_id, []))[:15]
                ],
                "risk": {"score": h.get("risk", 0.0), "reasons": h.get("reasons", [])}
                if h
                else None,
                "open_findings": [],
            }
        else:
            m = model.module_by_file.get(node_id)
            if m is None:
                continue
            h = model.health_files.get(node_id, {})
            pack = {
                "target": {"id": m["id"], "kind": "module", "file": node_id},
                "summary": m.get("doc", ""),
                "imports": sorted(imports.get(m["id"], [])),
                "imported_by": sorted(importers.get(m["id"], [])),
                "tests": model.tests_by_file.get(node_id, []),
                "symbols": [
                    {"id": sid, "kind": s["kind"]}
                    for sid, s in sorted(model.symbols.items())
                    if s["file"] == node_id and s["parent"] is None
                ][:20],
                "risk": {"score": h.get("risk", 0.0), "reasons": h.get("reasons", [])}
                if h
                else None,
                "open_findings": [],
            }
        details[node_id] = {
            "id": node_id,
            "pack": pack,
            "context_command": f"prism context {pack['target']['id']}",
            "dead": node_id in model.dead,
        }
    return details


def _embed_json(data: Any) -> str:
    text = json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    # Keep the payload inert inside <script>: no closing tags, no JS line terminators.
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def export_html(root: Path, out: Path, include_symbols: bool = False) -> dict[str, Any]:
    index_html = VIEWER_DIST / "index.html"
    if not index_html.is_file():
        raise UserError("viewer bundle missing; build it with `npm run build` in viewer/")
    model = GraphModel(root)
    levels = ["package", "file", *(["symbol"] if include_symbols else [])]
    payloads: dict[str, GraphPayload] = {}
    for level in levels:
        for layer in ("import", "call", "tests", "cochange"):
            if level == "symbol" and layer in ("import", "cochange"):
                continue
            payloads[f"{level}|{layer}"] = model.graph(layer=layer, level=level, node_cap=100_000)
    if include_symbols:
        payloads["symbol|import"] = payloads["symbol|call"]
    bundle = {
        "meta": {
            "project": root.resolve().name,
            "stats": {},
            "last_scan": None,
            "git": bool(model.last_changed),
            "has_routes": False,
            "static": True,
        },
        "graphs": {k: v.to_dict() for k, v in sorted(payloads.items())},
        "details": _static_details(model, list(payloads.values())),
    }
    html = index_html.read_text(encoding="utf-8")
    js = (
        (VIEWER_DIST / "assets" / "viewer.js")
        .read_text(encoding="utf-8")
        .replace("</script", "<\\/script")
    )
    css = (VIEWER_DIST / "assets" / "viewer.css").read_text(encoding="utf-8")
    html = re.sub(r'<script type="module"[^>]*src="\./assets/viewer\.js"></script>', "", html)
    html = re.sub(r'<link rel="stylesheet"[^>]*href="\./assets/viewer\.css">', "", html)
    inject = (
        f"<style>{css}</style>\n"
        f"<script>window.__PRISM_STATIC__ = {_embed_json(bundle)};</script>\n"
        f'<script type="module">{js}</script>\n'
    )
    html = html.replace("</body>", inject + "</body>")
    write_text(out, html)
    return {
        "path": str(out),
        "bytes": len(html.encode("utf-8")),
        "nodes": {k: len(v.nodes) for k, v in payloads.items()},
    }
