"""Compare legacy and compact rendering of the same delivered packet content."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from prism.navigator.api import op_task
from prism.navigator.task_pack import render_task
from tests.benchmarks.packet_audit import REQUESTS
from tests.benchmarks.replay_precision import (
    ROOT,
    historical_store,
    isolated_environment,
    parse_packet,
    provenance,
)


def legacy_render(pack: dict[str, Any]) -> str:
    """Restore old prefixes and repeated identities without changing delivered lines."""
    old = copy.deepcopy(pack)
    for block in old["blocks"]:
        if not block.get("source"):
            continue
        cursor = block["lines"][0]
        lines = []
        for line in block["source"].split("\n"):
            if omitted := re.match(r"^⋮ (\d+) lines omitted", line):
                cursor += int(omitted[1])
                lines.append(line)
                continue
            if numbered := re.match(r"^(\d+): ?", line):
                cursor = int(numbered[1])
                line = line[numbered.end() :]
            lines.append(f"{cursor}: {line}")
            cursor += 1
        block["source"] = "\n".join(lines)
    text = _legacy_formatter()(old)
    callers = [link for link in old.get("links", []) if link["role"] == "caller"]
    for link in callers:
        if link.get("uncertain"):
            text = text.replace(f"  {link['symbol']} ", f"  ~{link['symbol']} ")
    if any(link.get("uncertain") for link in callers):
        text = text.replace("\nNext:", "\n  ~ inferred caller; verify before changing\nNext:")
    return text


@lru_cache(maxsize=1)
def _legacy_formatter() -> Any:
    from prism.navigator import enrich
    from prism.navigator.overview import render_overview
    from prism.navigator.task_pack import _loc

    source = subprocess.run(
        ["git", "show", "da42c72:prism/navigator/task_pack.py"],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout
    node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "render_task"
    )
    namespace: dict[str, Any] = {
        "Any": Any,
        "enrich": enrich,
        "render_overview": render_overview,
        "_loc": _loc,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "T10-renderer", "exec"), namespace)
    return namespace["render_task"]


def audit(ref: str) -> dict[str, Any]:
    metadata = provenance(ROOT, ref)
    rows = []
    with tempfile.TemporaryDirectory(prefix="prism-format-audit-") as temp:
        base = Path(temp)
        with isolated_environment(base), historical_store(ROOT, base, ref) as store:
            for request in json.loads(REQUESTS.read_text(encoding="utf-8"))["requests"]:
                pack = op_task(store, request["query"], 2000, use_cache=False)
                compact, legacy = render_task(pack), legacy_render(pack)
                assert parse_packet(compact) == parse_packet(legacy), (
                    "formatting changed delivered source"
                )
                rows.append({**request, "legacy_chars": len(legacy), "compact_chars": len(compact)})
    before = sum(row["legacy_chars"] for row in rows)
    after = sum(row["compact_chars"] for row in rows)
    return {
        **metadata,
        "same_delivered_content": True,
        "rows": rows,
        "summary": {
            "legacy_chars": before,
            "compact_chars": after,
            "saving_pct": 100 * (before - after) / before,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
