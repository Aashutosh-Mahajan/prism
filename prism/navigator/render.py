"""Compact Markdown renderings of navigator results (the default CLI output)."""

from __future__ import annotations

from typing import Any


def _lines(lines: list[int] | None) -> str:
    if not lines:
        return ""
    return f":{lines[0]}" if lines[0] == lines[1] else f":{lines[0]}-{lines[1]}"


def render_locate(data: dict[str, Any]) -> str:
    out = [f"# locate `{data['query']}`"]
    for c in data["candidates"]:
        sig = f" — `{c['signature']}`" if c["signature"] and c["kind"] not in ("file",) else ""
        out.append(f"- [{c['match']}] {c['kind']} `{c['id']}` {c['file']}{_lines(c['lines'])}{sig}")
    return "\n".join(out)


def render_search(data: dict[str, Any]) -> str:
    out = [f'# search "{data["query"]}"']
    if not data["hits"]:
        out.append("No results.")
    for h in data["hits"]:
        loc = (
            f" {h['file']}{_lines(h.get('lines'))}" if h.get("file") and h["kind"] != "file" else ""
        )
        snippet = f" — {h['snippet']}" if h.get("snippet") else ""
        out.append(f"- {h['kind']} `{h['id']}`{loc}{snippet}")
    return "\n".join(out)


def render_context(pack: dict[str, Any]) -> str:
    t = pack["target"]
    out = [f"# Context: `{t['id']}`"]
    if "signature" in t:
        out.append(f"{t['kind']} `{t['signature']}` — {t['file']}{_lines(t['lines'])}")
    else:
        out.append(f"{t['kind']} {t['file']}")
    if pack.get("route"):
        out.append(f"Route: {pack['route']}")
    if pack.get("summary"):
        out.append(pack["summary"])
    risk = pack.get("risk")
    if risk and (risk["score"] or risk["reasons"]):
        out.append(
            f"Risk {risk['score']:.2f}"
            + (": " + "; ".join(risk["reasons"]) if risk["reasons"] else "")
        )
    if pack.get("open_findings"):
        out.append("Open findings: " + ", ".join(pack["open_findings"]))
    b = pack["budget"]
    out.append(f"\n## Read list ({b['used']}/{b['requested']} tokens)")
    for i, item in enumerate(pack["read_list"], 1):
        ref = f" `{item['id']}`" if item.get("id") and item["why"] != "target" else ""
        out.append(
            f"{i}. {item['file']}{_lines(item['lines'])} — {item['why']}{ref} (~{item['tokens_est']} tok)"
        )

    def section(title: str, rows: list[str], omitted: int = 0) -> None:
        if rows:
            out.append(f"\n## {title}")
            out.extend(rows)
            if omitted:
                out.append(f"- … {omitted} more")

    omitted = pack.get("omitted", {})
    section(
        "Callers",
        [
            f"- `{c['id']}` {c['file']}:{c['line']}"
            + ("" if c["confidence"] == "high" else f" ({c['confidence']})")
            for c in pack.get("callers", [])
        ],
        omitted.get("callers", 0),
    )
    section(
        "Callees",
        [f"- `{c['id']}` {c['file']}{_lines(c['lines'])}" for c in pack.get("callees", [])],
        omitted.get("callees", 0),
    )
    section("Members", [f"- `{m}`" for m in pack.get("members", [])])
    section(
        "Symbols",
        [f"- {s['kind']} `{s['signature']}`{_lines(s['lines'])}" for s in pack.get("symbols", [])],
        omitted.get("symbols", 0),
    )
    section("Imports", [f"- `{m}`" for m in pack.get("imports", [])])
    section("Imported by", [f"- `{m}`" for m in pack.get("imported_by", [])])
    section("Submodules", [f"- `{m}`" for m in pack.get("submodules", [])])
    section("Tests", [f"- {t}" for t in pack.get("tests", [])])
    section("Co-changed", [f"- {f}" for f in pack.get("co_changed", [])])
    section("Config read", [f"- {k}" for k in pack.get("config", [])])
    br = pack.get("blast_radius")
    if br and br["files"]:
        out.append(f"\n## Blast radius: {br['files']} files")
        out.extend(f"- {f}" for f in br["top"])
    if pack.get("source"):
        out.append(f"\n## Source\n```\n{pack['source']}\n```")
    return "\n".join(out)


def render_impact(data: dict[str, Any]) -> str:
    t = data["target"]
    totals = data["totals"]
    out = [
        f"# Impact: `{t['id']}`",
        f"{totals['symbols']} dependent symbols across {totals['files']} files"
        + (" (capped)" if totals["capped"] else ""),
    ]
    if data.get("risk"):
        r = data["risk"]
        out.append(
            f"Risk {r['score']:.2f}" + (": " + "; ".join(r["reasons"]) if r["reasons"] else "")
        )
    for level in data["dependents"]:
        out.append(f"\n## Distance {level['distance']}")
        out.extend(f"- `{s}`" for s in level["symbols"])
        if level["files"]:
            out.append("- files: " + ", ".join(level["files"]))
        if level["omitted"]:
            out.append(f"- … {level['omitted']} more")
    out.append("\n## Tests to run")
    out.extend([f"- {t}" for t in data["tests"]] or ["- none mapped"])
    return "\n".join(out)


def render_brief(data: dict[str, Any]) -> str:
    return f"{data['brief'].rstrip()}\n\n{data['freshness']}\n"
