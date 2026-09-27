"""Structural snapshots and diffs: the facts whose change makes narrative stale.

A snapshot is built from the artifact documents (the same dicts written to
`.aicontext/`), so it can be rebuilt from committed files on a fresh clone.
Line numbers, bodies, formatting and comments are deliberately absent:
edits that only touch those never produce drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TOP_N = 20


@dataclass(frozen=True)
class Change:
    kind: str
    weight: int
    sections: tuple[str, ...]
    description: str
    ids: tuple[str, ...] = field(default=())


def _group_of(module: str, is_package: bool, packages: set[str]) -> str:
    if is_package:
        return module
    parent = module.rsplit(".", 1)[0] if "." in module else ""
    return parent if parent in packages else module


def snapshot(docs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tests = set(docs.get("tests_map.json", {}).get("test_files", []))
    dep = docs.get("dependency_graph.json", {})
    modules = [m for m in dep.get("modules", []) if m["file"] not in tests]
    packages = {m["id"] for m in modules if m["is_package"]}
    groups = {m["id"]: _group_of(m["id"], m["is_package"], packages) for m in modules}
    symbols = [s for s in docs.get("symbols.json", {}).get("symbols", []) if s["file"] not in tests]
    public = {s["id"]: s["signature"] for s in symbols if s["visibility"] == "public"}
    top = sorted(symbols, key=lambda s: (-s["rank"], s["id"]))[:TOP_N]
    edges = sorted(
        f"{e['from']} -> {e['to']}"
        for e in dep.get("edges", [])
        if e["from"] in groups and e["to"] in groups
    )
    return {
        "modules": sorted(groups),
        "groups": groups,
        "public": public,
        "symbol_module": {s["id"]: s["module"] for s in symbols if s["visibility"] == "public"},
        "routes": sorted(
            f"{r['method']} {r['path']}" for r in docs.get("routes.json", {}).get("routes", [])
        ),
        "models": sorted(m["id"] for m in docs.get("models.json", {}).get("models", [])),
        "config": sorted(k["key"] for k in docs.get("config.json", {}).get("keys", [])),
        "import_edges": edges,
        "top": [s["id"] for s in top],
        "deps": sorted(dep.get("declared_dependencies", [])),
        "entry_points": sorted(
            f"{ep['kind']}:{ep['name'] or ep['symbol'] or ep['module']}"
            for ep in dep.get("entry_points", [])
        ),
    }


def _module_section(snap: dict[str, Any], module: str) -> str:
    return f"modules/{snap['groups'].get(module, module)}"


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []

    def added_removed(key: str) -> tuple[list[str], list[str]]:
        a, b = set(old.get(key, [])), set(new.get(key, []))
        return sorted(b - a), sorted(a - b)

    added, removed = added_removed("modules")
    for m in added:
        changes.append(
            Change(
                "module_added",
                5,
                ("architecture", _module_section(new, m)),
                f"new module `{m}`",
                (m,),
            )
        )
    for m in removed:
        changes.append(
            Change(
                "module_removed",
                5,
                ("architecture", _module_section(old, m)),
                f"module `{m}` removed",
                (m,),
            )
        )

    old_pub: dict[str, str] = old.get("public", {})
    new_pub: dict[str, str] = new.get("public", {})
    gone = sorted(set(old_pub) - set(new_pub))
    fresh = sorted(set(new_pub) - set(old_pub))
    top = set(new.get("top", [])) | set(old.get("top", []))

    def tail(sig: str) -> str:
        return sig[sig.find("(") :] if "(" in sig else sig

    renamed: set[str] = set()
    for g in gone:
        g_mod = old.get("symbol_module", {}).get(g)
        for f in fresh:
            if f in renamed:
                continue
            if new.get("symbol_module", {}).get(f) == g_mod and tail(old_pub[g]) == tail(
                new_pub[f]
            ):
                renamed.update({g, f})
                sections = (_module_section(new, g_mod or ""),) + (
                    ("architecture",) if g in top else ()
                )
                changes.append(
                    Change("public_renamed", 2, sections, f"`{g}` renamed to `{f}`", (f,))
                )
                break
    for sid in fresh:
        if sid in renamed:
            continue
        mod = new.get("symbol_module", {}).get(sid, "")
        sections = (_module_section(new, mod),) + (("architecture",) if sid in top else ())
        changes.append(Change("public_added", 2, sections, f"new public symbol `{sid}`", (sid,)))
    for sid in gone:
        if sid in renamed:
            continue
        mod = old.get("symbol_module", {}).get(sid, "")
        sections = (_module_section(old, mod),) + (("architecture",) if sid in top else ())
        changes.append(
            Change("public_removed", 2, sections, f"public symbol `{sid}` removed", (sid,))
        )
    for sid in sorted(set(old_pub) & set(new_pub)):
        if old_pub[sid] != new_pub[sid]:
            mod = new.get("symbol_module", {}).get(sid, "")
            changes.append(
                Change(
                    "signature_changed",
                    2,
                    (_module_section(new, mod),),
                    f"signature of `{sid}` is now `{new_pub[sid]}`",
                    (sid,),
                )
            )

    for key, label in (("routes", "route"), ("models", "model"), ("config", "config key")):
        a, r = added_removed(key)
        for item in a:
            changes.append(
                Change(f"{key}_added", 3, ("architecture",), f"new {label} `{item}`", (item,))
            )
        for item in r:
            changes.append(
                Change(f"{key}_removed", 3, ("architecture",), f"{label} `{item}` removed", (item,))
            )

    a, r = added_removed("import_edges")
    edge_changes = [f"import `{e}` added" for e in a] + [f"import `{e}` removed" for e in r]
    for i, desc in enumerate(edge_changes):
        # 1 point per edge, capped at 5 per update.
        changes.append(Change("import_edge", 1 if i < 5 else 0, ("architecture",), desc))

    old_top, new_top = set(old.get("top", [])), set(new.get("top", []))
    if old_top:  # no "entered the top 20" noise on the very first comparison
        for sid in sorted(new_top - old_top):
            changes.append(
                Change(
                    "top_entered",
                    3,
                    ("architecture",),
                    f"`{sid}` is now among the most important symbols",
                    (sid,),
                )
            )
        for sid in sorted(old_top - new_top):
            changes.append(
                Change(
                    "top_left",
                    3,
                    ("architecture",),
                    f"`{sid}` left the most important symbols",
                    (sid,),
                )
            )

    a, _ = added_removed("deps")
    for dep in a:
        changes.append(
            Change(
                "dependency_added", 3, ("architecture", "conventions"), f"new dependency `{dep}`"
            )
        )
    a, r = added_removed("entry_points")
    for ep in a + r:
        changes.append(
            Change(
                "entry_point_changed",
                3,
                ("purpose",),
                f"entry point `{ep}` {'added' if ep in a else 'removed'}",
            )
        )
    return changes
