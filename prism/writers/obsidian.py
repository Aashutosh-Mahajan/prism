"""`prism graph export --obsidian <dir>`: the codebase as an Obsidian vault.

One note per module (optionally per class/function) with YAML frontmatter,
tags, and [[wikilinks]] for imports and calls, so Obsidian's graph view,
backlinks, and search work over the code. Deterministic file names; re-export
updates notes in place and removes notes for deleted modules/symbols. Only
notes carrying `prism: generated` are ever touched or removed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from prism.core.errors import UserError
from prism.viewer.model import GraphModel
from prism.writers.json_writer import write_text

MARKER = "prism: generated"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def note_name(ident: str) -> str:
    name = _SAFE.sub("_", ident)
    return f"module--{name}" if name.lower() in {"index", "readme"} else name


def _risk_tag(risk: float) -> str:
    return "high" if risk >= 0.6 else ("medium" if risk >= 0.35 else "low")


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---", MARKER]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {json.dumps(v, ensure_ascii=False)}" for v in value)
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _is_generated(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8")[:200]
    except OSError:
        return False
    return head.startswith("---") and MARKER in head


def _write_note(path: Path, text: str) -> None:
    if path.exists() and not _is_generated(path):
        raise UserError(f"vault note belongs to the user: {path}")
    write_text(path, text)


def export_obsidian(
    root: Path, out: Path, include_symbols: bool = False, graph_colors: bool = False
) -> dict[str, int]:
    model = GraphModel(root)
    out.mkdir(parents=True, exist_ok=True)
    imports: dict[str, list[str]] = {}
    imported_by: dict[str, list[str]] = {}
    for a, b in model.import_edges:
        imports.setdefault(a, []).append(b)
        imported_by.setdefault(b, []).append(a)
    by_file: dict[str, list[dict[str, Any]]] = {}
    for s in model.symbols.values():
        by_file.setdefault(s["file"], []).append(s)
    calls: dict[str, list[str]] = {}
    called_by: dict[str, list[str]] = {}
    for a, b, _ in model.call_edges:
        calls.setdefault(a, []).append(b)
        called_by.setdefault(b, []).append(a)

    written: set[Path] = set()
    for mid, m in sorted(model.modules.items()):
        path = m["file"]
        h = model.health_files.get(path, {})
        group = model.group_of_module[mid]
        tags = [
            f"module/{group.replace('.', '/')}",
            f"risk/{_risk_tag(h.get('risk', 0.0))}",
            "kind/module",
        ]
        if path in model.test_files:
            tags.append("kind/test")
        body = [
            _frontmatter(
                {
                    "type": "module",
                    "path": path,
                    "lines": [1, m.get("loc", 0)],
                    "callers": sorted(set(imported_by.get(mid, []))),
                    "tests": sorted(set(model.tests_by_file.get(path, []))),
                    "id": mid,
                    "file": path,
                    "kind": "test" if path in model.test_files else "module",
                    "rank": m["rank"],
                    "risk": h.get("risk", 0.0),
                    "loc": m.get("loc", 0),
                    "owner": (h.get("owners") or [None])[0],
                    "language": model.language_of.get(path, "python"),
                    "tags": tags,
                }
            ),
            f"# {mid}",
            "",
            m.get("doc") or "",
            "",
            f"`{path}`",
            "",
        ]
        if imports.get(mid):
            body += ["## Imports", *(f"- [[{note_name(t)}]]" for t in sorted(imports[mid])), ""]
        if imported_by.get(mid):
            body += [
                "## Imported by",
                *(f"- [[{note_name(t)}]]" for t in sorted(imported_by[mid])),
                "",
            ]
        syms = sorted(
            (s for s in by_file.get(path, []) if s["parent"] is None), key=lambda s: s["lines"][0]
        )
        if syms:
            body.append("## Symbols")
            for s in syms:
                link = (
                    f"[[{note_name(s['id'])}|{s['id'].rsplit('.', 1)[-1]}]]"
                    if include_symbols
                    else f"`{s['signature']}`"
                )
                doc = f" — {s['doc']}" if s["doc"] else ""
                body.append(f"- {link}{doc}")
            body.append("")
        tests = model.tests_by_file.get(path, [])
        if tests:
            body += [
                "## Tests",
                *(
                    f"- [[{note_name(model.module_by_file[t]['id'])}]]"
                    for t in tests
                    if t in model.module_by_file
                ),
                "",
            ]
        target = out / f"{note_name(mid)}.md"
        _write_note(target, "\n".join(body).rstrip() + "\n")
        written.add(target)

    if include_symbols:
        sym_dir = out / "symbols"
        for sid, s in sorted(model.symbols.items()):
            if s["kind"] == "method" and not calls.get(sid) and not called_by.get(sid):
                continue
            h = model.health_symbols.get(sid, {})
            body = [
                _frontmatter(
                    {
                        "type": "symbol",
                        "path": s["file"],
                        "callers": sorted(set(called_by.get(sid, []))),
                        "tests": sorted(set(model.tests_by_file.get(s["file"], []))),
                        "id": sid,
                        "file": s["file"],
                        "lines": s["lines"],
                        "kind": s["kind"],
                        "rank": s["rank"],
                        "risk": h.get("risk", 0.0),
                        "tags": [f"kind/{s['kind']}", f"risk/{_risk_tag(h.get('risk', 0.0))}"],
                    }
                ),
                f"# {sid}",
                "",
                f"`{s['signature']}` — `{s['file']}:{s['lines'][0]}`",
                "",
                s["doc"] or "",
                "",
                f"Module: [[{note_name(s['module'])}]]",
                "",
            ]
            if calls.get(sid):
                body += ["## Calls", *(f"- [[{note_name(c)}]]" for c in sorted(calls[sid])), ""]
            if called_by.get(sid):
                body += [
                    "## Called by",
                    *(f"- [[{note_name(c)}]]" for c in sorted(called_by[sid])),
                    "",
                ]
            target = sym_dir / f"{note_name(sid)}.md"
            _write_note(target, "\n".join(body).rstrip() + "\n")
            written.add(target)

    clusters: dict[str, list[str]] = {}
    for mid in sorted(model.modules):
        clusters.setdefault(model.group_of_module[mid], []).append(mid)
    for group, members in sorted(clusters.items()):
        target = out / "clusters" / f"{note_name(group)}.md"
        body = [
            _frontmatter(
                {
                    "type": "cluster",
                    "path": group,
                    "kind": "module-group",
                    "lines": [],
                    "callers": [],
                    "tests": [],
                }
            ),
            f"# {group}",
            "",
            "## Members",
            *(f"- [[{note_name(member)}]]" for member in members),
        ]
        _write_note(target, "\n".join(body) + "\n")
        written.add(target)
    target = out / "index.md"
    body = [
        _frontmatter(
            {"type": "index", "path": "", "kind": "vault", "lines": [], "callers": [], "tests": []}
        ),
        "# Code index",
        "",
        f"{len(model.modules)} modules · {len(model.symbols)} symbols · {len(clusters)} clusters",
        "",
        *(
            f"- [[clusters/{note_name(group)}|{group}]] ({len(members)} modules)"
            for group, members in sorted(clusters.items())
        ),
    ]
    _write_note(target, "\n".join(body) + "\n")
    written.add(target)
    target = out / "README.md"
    _write_note(
        target,
        _frontmatter(
            {
                "type": "guide",
                "path": "",
                "kind": "human-view",
                "lines": [],
                "callers": [],
                "tests": [],
            }
        )
        + "\n# PRISM vault\n\nStart at [[index]]. Cluster notes link to module members; optional symbols/ notes link calls and callers. Frontmatter uses type, path, kind, lines, callers and tests for Dataview. Re-export updates generated notes; keep personal notes in separate files.\n\nThis is a human view. Agents retrieve task packets instead of loading this vault.\n",
    )
    written.add(target)
    removed = 0
    for note in out.rglob("*.md"):
        if note not in written and ".obsidian" not in note.parts and _is_generated(note):
            note.unlink()
            removed += 1
    if graph_colors:
        colors = [
            {"query": f"tag:#risk/{level}", "color": {"a": 1, "rgb": rgb}}
            for level, rgb in (("high", 0xD63448), ("medium", 0xE2C448), ("low", 0x4EAD78))
        ]
        graph_path = out / ".obsidian" / "graph.json"
        current: dict[str, Any] = {}
        if graph_path.is_file():
            try:
                current = json.loads(graph_path.read_text(encoding="utf-8"))
            except ValueError:
                current = {}
        current["colorGroups"] = colors
        write_text(graph_path, json.dumps(current, indent=2) + "\n")
    return {"notes": len(written), "removed": removed}
