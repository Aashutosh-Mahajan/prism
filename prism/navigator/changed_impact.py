"""Read-only working-tree impact using indexed symbols and both Git diff stages."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.navigator.impact import impact
from prism.navigator.resolve import Target
from prism.navigator.store import IndexStore

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def diff_ranges(diff: str) -> dict[str, list[tuple[int, int]]]:
    """Both coordinates conservatively cover an index before or after the edit."""
    result: dict[str, list[tuple[int, int]]] = {}
    old = new = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            old = _diff_path(line[4:], "a/")
        elif line.startswith("+++ "):
            new = _diff_path(line[4:], "b/")
        elif match := _HUNK.match(line):
            for file, start, count in (
                (old, int(match[1]), int(match[2] or 1)),
                (new, int(match[3]), int(match[4] or 1)),
            ):
                if file:
                    result.setdefault(file, []).append(
                        (max(1, start), max(1, start + max(1, count) - 1))
                    )
    return result


def _diff_path(value: str, prefix: str) -> str | None:
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        # core.quotePath=false still quotes tabs/newlines; Git's C escape syntax.
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value[len(prefix) :] if value.startswith(prefix) else None


def changed_impact(store: IndexStore, budget: int = 1200) -> dict[str, Any]:
    if not 128 <= budget <= 32000:
        raise UserError("impact budget must be 128–32000")
    ranges: dict[str, list[tuple[int, int]]] = {}
    stages: list[list[str]] = [[], ["--cached"]]
    for extra in stages:
        run = subprocess.run(
            [
                "git",
                "-c",
                "core.quotePath=false",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "-U0",
                *extra,
                "--",
            ],
            cwd=store.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if run.returncode:
            raise UserError("cannot read the working-tree Git diff")
        for file, spans in diff_ranges(run.stdout).items():
            ranges.setdefault(file, []).extend(spans)
    rows = []
    unmapped = []
    for file in sorted(ranges):
        symbols = [
            symbol
            for symbol in store.symbols_in_file(file)
            if any(lo <= symbol.end and hi >= symbol.start for lo, hi in ranges[file])
        ]
        if not symbols:
            unmapped.append(file)
        for symbol in symbols:
            view = impact(store, Target("symbol", file, symbol=symbol), depth=1)
            callers = sorted({link.symbol.id for link in store.callers(symbol.id)})
            reasons = []
            if symbol.visibility == "public":
                reasons.append("public symbol changed")
            if len(callers) >= 5:
                reasons.append("many callers")
            if not view["tests"]:
                reasons.append("no indexed test")
            rows.append(
                {
                    "symbol": symbol.id,
                    "file": file,
                    "lines": [symbol.start, symbol.end],
                    "risk": reasons,
                    "callers": callers[:6],
                    "callers_omitted": max(0, len(callers) - 6),
                    "tests": view["tests"][:3],
                    "tests_omitted": max(0, len(view["tests"]) - 3),
                }
            )
    rows.sort(key=lambda row: (-len(row["risk"]), row["file"], row["symbol"]))
    result: dict[str, Any] = {
        "changed": [],
        "symbols_total": len(rows),
        "symbols_omitted": len(rows),
        "unmapped_files": [],
        "unmapped_omitted": len(unmapped),
        "coordinates": "old/new conservative; indexed symbol ranges",
        "budget": budget,
    }
    for row in rows:
        result["changed"].append(row)
        result["symbols_omitted"] -= 1
        if _size(result) > budget:
            result["changed"].pop()
            result["symbols_omitted"] += 1
    for file in unmapped:
        result["unmapped_files"].append(file)
        result["unmapped_omitted"] -= 1
        if _size(result) > budget:
            result["unmapped_files"].pop()
            result["unmapped_omitted"] += 1
    return result


def render_changed_impact(result: dict[str, Any]) -> str:
    lines = [
        f"Changed impact: {result['symbols_total']} indexed symbols ({result['symbols_omitted']} omitted)"
    ]
    for row in result["changed"]:
        lines.append(
            f"{row['symbol']} ({row['file']}:{row['lines'][0]}): " + ", ".join(row["risk"])
        )
        if row["callers"]:
            lines.append("  Callers: " + ", ".join(row["callers"]))
        if row["tests"]:
            lines.append("  Tests: " + ", ".join(row["tests"]))
    if result["unmapped_files"]:
        lines.append("Unmapped: " + ", ".join(result["unmapped_files"]))
    lines.append(result["coordinates"])
    return "\n".join(lines)


def _size(result: dict[str, Any]) -> int:
    return max(
        estimate_tokens(json.dumps(result, separators=(",", ":"))),
        estimate_tokens(render_changed_impact(result)),
    )
