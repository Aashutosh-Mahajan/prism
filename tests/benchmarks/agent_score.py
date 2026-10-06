"""Score archived answers against the plan's fixed primary/alternative function key.

Caller coverage is textual name matching, not a runtime call-graph guarantee.
Existing-test mentions are recorded separately from suggestions for new tests.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ALTERNATIVES = {
    5: ["OrderViewSet.update_status"],
    6: ["grouped_by_bucket", "RestaurantViewSet.summary"],
    8: ["get_window", "Window.previous"],
}


def mentions(text: str, symbol: str) -> bool:
    name = symbol.rsplit(".", 1)[-1]
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def matches_primary(text: str, symbol: str) -> bool:
    if not mentions(text, symbol):
        return False
    parts = symbol.split(".")
    owner = parts[-2] if len(parts) > 1 else ""
    return not (owner and owner[0].isupper()) or mentions(text, owner)


def sections(text: str) -> dict[int, str]:
    starts = list(
        re.finditer(r"(?m)^(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:Task\s+)?(\d+)[.):]", text)
    )
    return {
        int(match.group(1)): text[
            match.start() : starts[i + 1].start() if i + 1 < len(starts) else len(text)
        ]
        for i, match in enumerate(starts)
    }


def score(output: Path) -> dict:
    result = {}
    for run in range(1, 4):
        base = output / f"run-{run}"
        key = json.loads((base / "answer-key.json").read_text(encoding="utf-8"))
        test_names = set()
        for path in (base / "without" / "backend").rglob("test*.py"):
            relative = path.relative_to(base / "without" / "backend")
            test_names.add(".".join(relative.with_suffix("").parts))
            test_names.add("backend/" + relative.as_posix())
            test_names.update(re.findall(r"^class\s+(\w+)", path.read_text(encoding="utf-8"), re.M))
        for side in ("without", "with"):
            path = output / f"run{run}_{side}-answer.md"
            if not path.exists():
                continue
            parts = sections(path.read_text(encoding="utf-8"))
            if set(parts) != set(range(1, 13)):
                raise ValueError(f"Cannot parse all 12 tasks: {path}")
            rows = []
            for expected in key:
                number = expected["task"]
                section = parts[number]
                primary_match = re.search(r"(?im)primary(?:\s+function)?[^\w\n]*([^\n]+)", section)
                if not primary_match:
                    raise ValueError(f"Missing primary function: {path}, task {number}")
                primary = re.split(r";|,\s*location\s*=|[—–]", primary_match.group(1))[0]
                accepted = [expected["target"], *ALTERNATIVES.get(number, [])]
                grade = (
                    "correct"
                    if any(matches_primary(primary, name) for name in accepted)
                    else ("partial" if mentions(section, expected["target"]) else "wrong")
                )
                callers = expected["direct_callers"]
                named = [s for s in callers if mentions(section, s)]
                tests = re.search(r"(?im)tests(?:\s+to\s+run)?[^\w\n]*([^\n]+)", section)
                test_text = tests.group(1) if tests else ""
                found = sorted(
                    name
                    for name in test_names
                    if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", test_text)
                )
                rows.append(
                    {
                        "task": number,
                        "primary": primary,
                        "grade": grade,
                        "direct_callers_named": named,
                        "direct_callers_total": len(callers),
                        "existing_backend_tests_named": found,
                    }
                )
            result[f"run{run}_{side}"] = {
                "correct": sum(r["grade"] == "correct" for r in rows),
                "partial": sum(r["grade"] == "partial" for r in rows),
                "wrong": sum(r["grade"] == "wrong" for r in rows),
                "direct_callers_named_count": sum(len(r["direct_callers_named"]) for r in rows),
                "direct_callers_total_count": sum(r["direct_callers_total"] for r in rows),
                "tasks_with_existing_backend_tests_named": sum(
                    bool(r["existing_backend_tests_named"]) for r in rows
                ),
                "tasks": rows,
            }
    (output / "scores.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(score(args.output), indent=2))
