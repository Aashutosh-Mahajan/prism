"""Measure native Codex subagent rollouts, without trusting agent self-reports.

Usage: python -m tests.benchmarks.agent_measure TRANSCRIPT [TRANSCRIPT ...]
Codex input_tokens includes cached tokens. Billable equivalent uses the plan's
0.1 cached-read multiplier as a comparison proxy, not a price quote.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def records(path: Path) -> list[dict[str, Any]]:
    result = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                result.append(json.loads(line))
            except ValueError:
                continue  # A live transcript can end with a partially written line.
    return result


def summarise(path: Path) -> dict[str, Any]:
    rows = records(path)
    usages = []
    seen_responses: set[str] = set()
    seen_calls: set[str] = set()
    seen_outputs: set[str] = set()
    tools: collections.Counter[str] = collections.Counter()
    output_chars = 0
    shell_calls = 0
    prism_cli_sites = 0
    final = []
    models = set()
    effort = set()
    agent = None
    for row in rows:
        payload = row.get("payload", {})
        kind = row.get("type")
        if kind == "session_meta":
            agent = payload.get("agent_path")
        if kind == "turn_context":
            if payload.get("model"):
                models.add(payload["model"])
            if payload.get("effort"):
                effort.add(payload["effort"])
        if kind == "token_usage_record":
            identity = payload.get("response_id")
            if identity and identity not in seen_responses:
                seen_responses.add(identity)
                usages.append(payload["usage"])
        if kind != "response_item":
            continue
        item = payload.get("type")
        identity = payload.get("call_id")
        if item in ("function_call", "custom_tool_call") and identity not in seen_calls:
            seen_calls.add(identity)
            tools[payload.get("name", "unknown")] += 1
            source = payload.get("input", payload.get("arguments", ""))
            shell_calls += source.count("tools.exec_command(")
            prism_cli_sites += len(
                re.findall(
                    r"(?<!\w)prism\s+(?:brief|search|locate|context|impact|module|init|scan|update|enable)\b",
                    source,
                )
            )
        if (
            item in ("function_call_output", "custom_tool_call_output")
            and identity not in seen_outputs
        ):
            seen_outputs.add(identity)
            output = payload.get("output", "")
            output_chars += len(output if isinstance(output, str) else json.dumps(output))
        if (
            item == "message"
            and payload.get("role") == "assistant"
            and (payload.get("channel") == "final" or payload.get("phase") == "final_answer")
        ):
            final.extend(c["text"] for c in payload.get("content", []) if "text" in c)
    contexts = [int(u.get("input_tokens", 0)) for u in usages]
    cached = sum(int(u.get("cached_input_tokens", 0)) for u in usages)
    writes = sum(int(u.get("cache_write_input_tokens", 0)) for u in usages)
    total_input = sum(contexts)
    stamps = [r["timestamp"] for r in rows if r.get("timestamp")]
    duration = None
    if stamps:
        duration = (
            datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
            - datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))
        ).total_seconds()
    return {
        "agent": agent,
        "models": sorted(models),
        "effort": sorted(effort),
        "model_turns": len(usages),
        "total_input_processed": total_input,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": writes,
        "billable_input_equiv_proxy": round(total_input - cached + cached * 0.1 + writes * 0.25),
        "first_turn_context": contexts[0] if contexts else None,
        "last_turn_context": contexts[-1] if contexts else None,
        "work_context": contexts[-1] - contexts[0] if contexts else None,
        "output_tokens": sum(int(u.get("output_tokens", 0)) for u in usages),
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "nested_shell_call_sites": shell_calls,
        "prism_cli_command_sites": prism_cli_sites,
        "tool_output_chars": output_chars,
        "tool_output_tokens_est": output_chars // 4,
        "started": stamps[0] if stamps else None,
        "finished": stamps[-1] if stamps else None,
        "duration_seconds": round(duration, 3) if duration is not None else None,
        "final_answer": "\n".join(final),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcripts", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps({str(p): summarise(p) for p in args.transcripts}, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)
