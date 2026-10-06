"""Archive and measure benchmark subagents belonging to one Codex parent chat."""

from __future__ import annotations

import argparse
import collections
import json
import shutil
from pathlib import Path

from tests.benchmarks.agent_measure import records, summarise
from tests.benchmarks.agent_prepare import hashes


def mcp_metrics(path: Path) -> dict:
    rows = records(path)
    calls = {}
    responses = {}
    starts = 0
    client_closed = False
    server_exited = False
    for row in rows:
        message = row.get("message", {})
        if row.get("direction") == "lifecycle" and message.get("event") == "server_started":
            starts += 1
        if row.get("direction") == "lifecycle" and message.get("event") == "client_close":
            client_closed = True
        if row.get("direction") == "lifecycle" and message.get("event") == "server_exit":
            server_exited = True
        if row.get("direction") == "send" and message.get("method") == "tools/call":
            calls[message["id"]] = message["params"]["name"]
        if row.get("direction") == "receive" and message.get("id") in calls:
            responses[message["id"]] = message
    counts = collections.Counter(calls.values())
    application_errors = collections.Counter()
    for row in responses.values():
        result = row.get("result", {})
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and structured.get("error"):
            application_errors[structured["error"]] += 1
    return {
        "mcp_server_starts": starts,
        "mcp_client_closed": client_closed,
        "mcp_server_exited": server_exited,
        "mcp_tool_calls": len(calls),
        "mcp_tools": dict(counts),
        "mcp_tool_responses": len(responses),
        "mcp_protocol_errors": sum("error" in row for row in responses.values()),
        "mcp_tool_errors": sum(
            bool(row.get("result", {}).get("isError")) for row in responses.values()
        ),
        "mcp_application_errors": dict(application_errors),
    }


def collect(session_dir: Path, parent: str, output: Path, agent_prefix: str = "") -> None:
    summaries = {}
    archive = output / "transcripts"
    archive.mkdir(exist_ok=True)
    for path in session_dir.glob("*.jsonl"):
        rows = records(path)
        meta = next((r["payload"] for r in rows if r["type"] == "session_meta"), {})
        full_name = meta.get("agent_path", "").rsplit("/", 1)[-1]
        if not full_name.startswith(agent_prefix):
            continue
        name = full_name[len(agent_prefix) :]
        if meta.get("parent_thread_id") != parent or name not in {
            f"run{run}_{side}" for run in range(1, 4) for side in ("with", "without")
        }:
            continue
        summary = summarise(path)
        if not summary["final_answer"]:
            continue
        destination = archive / f"{name}.jsonl"
        shutil.copyfile(path, destination)
        summary["transcript"] = str(destination)
        (output / f"{name}-answer.md").write_text(summary.pop("final_answer"), encoding="utf-8")
        run, side = name.split("_")
        base = output / f"run-{run[3:]}"
        expected = json.loads((base / "integrity.json").read_text(encoding="utf-8"))[side]
        actual = hashes(base / side)
        trace = base / side / ".aicontext" / "benchmark-mcp.jsonl"
        if trace.exists():
            summary.update(mcp_metrics(trace))
            shutil.copyfile(trace, archive / f"{name}-mcp.jsonl")
        summary["source_integrity_passed"] = expected == actual
        summary["changed_files"] = sorted(
            k for k in expected.keys() | actual.keys() if expected.get(k) != actual.get(k)
        )
        summaries[name] = summary
    (output / "metrics.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-prefix", default="")
    args = parser.parse_args()
    collect(args.session_dir, args.parent, args.output, args.agent_prefix)
