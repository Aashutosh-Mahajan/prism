"""Prepare isolated copies and hidden scoring data for the live agent benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_impact
from prism.navigator.store import IndexStore

IGNORE = shutil.ignore_patterns(
    ".git",
    ".claude",
    ".codex",
    ".kiro",
    ".aicontext",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".*_cache",
    ".env",
    ".env.*",
    "Claude outputs",
    "Stitch_Screens",
    "sqlite_migration_dump.json",
)


def hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".aicontext" not in p.relative_to(root).parts
    }


def prepare(source: Path, plan: Path, output: Path, transport: str = "cli") -> None:
    if output.exists():
        raise SystemExit(f"Refusing to overwrite an existing run directory: {output}")
    if output == source or source in output.parents:
        raise SystemExit("Output must be outside the source repository")
    text = plan.read_text(encoding="utf-8")
    task_block = re.search(r"```json\s*(\[.*?\])\s*```", text, re.S)
    if task_block is None:
        raise SystemExit("Plan has no task JSON block")
    tasks = json.loads(task_block.group(1))
    reports = re.findall(r'^\| \d+ \| "(.*?)" \|', text, re.M)
    if len(tasks) != 12 or len(reports) != 12:
        raise SystemExit("Expected exactly 12 task reports and targets")
    output.mkdir(parents=True)
    (output / "provenance.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "plan": str(plan),
                "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "repetitions": 3,
                "transport": transport,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "tasks.json").write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    (output / "reports.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    previous = os.environ.get("PRISM_CONFIG_HOME")
    try:
        for run in range(1, 4):
            base = output / f"run-{run}"
            without = base / "without"
            with_prism = base / "with"
            shutil.copytree(source, without, ignore=IGNORE)
            shutil.copytree(without, with_prism)
            before = hashes(without)
            assert before == hashes(with_prism), "Repository copies differ"
            os.environ["PRISM_CONFIG_HOME"] = str(base / "cfg")
            apply_init(plan_init(with_prism))
            manifest = scan(with_prism)
            if transport == "mcp":
                shutil.copyfile(
                    Path(__file__).with_name("prism_mcp_client.mjs"),
                    with_prism / ".aicontext" / "benchmark-client.mjs",
                )
            indexed_symbols = {
                entry["id"]: entry
                for entry in json.loads(
                    (with_prism / ".aicontext" / "symbols.json").read_text(encoding="utf-8")
                )["symbols"]
            }
            store = IndexStore.open(with_prism)
            try:
                key = []
                for number, task in enumerate(tasks, 1):
                    symbol = store.symbol(task["target"])
                    if symbol is None:
                        raise SystemExit(f"Missing target: {task['target']}")
                    key.append(
                        {
                            "task": number,
                            "target": task["target"],
                            "file": symbol.file,
                            "start": symbol.lines[0],
                            "end": symbol.lines[1],
                            "direct_callers": indexed_symbols[task["target"]]["called_by"],
                            "impact": op_impact(store, task["target"]),
                        }
                    )
            finally:
                store.close()
            (base / "answer-key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
            (base / "integrity.json").write_text(
                json.dumps(
                    {
                        "without": before,
                        "with": hashes(with_prism),
                        "indexed_files": len(manifest["files"]),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"Run {run}: prepared and indexed {len(manifest['files'])} files", flush=True)
    finally:
        if previous is None:
            os.environ.pop("PRISM_CONFIG_HOME", None)
        else:
            os.environ["PRISM_CONFIG_HOME"] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=("cli", "mcp"), default="cli")
    args = parser.parse_args()
    prepare(args.repo.resolve(), args.plan.resolve(), args.output.resolve(), args.transport)
