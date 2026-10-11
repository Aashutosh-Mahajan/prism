"""Offline integration preflight for any prepared base/indexed/hidden campaign.

No model calls. Query CLI, actual stdio MCP, and prompt hooks on a disposable
copy, and retain measurements outside that copy before automatic cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from prism.core.tokens import estimate_tokens
from prism.navigator.freshness import caches_ready, warm_caches
from prism.writers.worklog import sessions

PRISM = Path(os.environ.get("PRISM_UNDER_TEST", Path(__file__).resolve().parents[2])).resolve()


def ignore(directory: str, names: list[str]) -> list[str]:
    skipped = [n for n in names if n == "__pycache__" or n.endswith(".pyc")]
    if Path(directory).name == ".aicontext" and "cache" in names:
        skipped.append("cache")
    return skipped


def summary(pack: dict) -> dict:
    return {
        "error": pack.get("error"),
        "confidence": pack.get("confidence"),
        "sufficient": pack.get("sufficient"),
        "estimated_tokens": pack.get("budget", {}).get("used_est"),
        "source_files": sorted({b["file"] for b in pack.get("blocks", []) if b.get("source")}),
        "literal_files": sorted(
            {o["file"] for lit in pack.get("literals", []) for o in lit.get("occurrences", [])}
        ),
        "partial": bool(pack.get("search_limited") or pack.get("stale_sources")),
        "has_evidence": bool(pack.get("blocks") or pack.get("literals") or pack.get("overview")),
    }


async def mcp_queries(
    root: Path, env: dict[str, str], tasks: list[dict], budget: int
) -> list[dict]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-X", "utf8", "-m", "prism", "mcp", "--root", str(root)],
        env=env,
        cwd=str(root),
    )
    results = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        for task in tasks:
            start = time.perf_counter()
            result = await client.call_tool(
                "prism_task",
                {
                    "query": task["request"],
                    "budget": budget,
                    "format": "json",
                    "repeat": True,
                },
            )
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            pack = json.loads(text)
            results.append(
                {
                    "task": task["id"],
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                    "transport_error": bool(
                        getattr(result, "is_error", getattr(result, "isError", False))
                    ),
                    **summary(pack),
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=2000)
    parser.add_argument("--require-hooks", action="store_true")
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    tasks = json.loads((campaign / "hidden/tasks.json").read_text(encoding="utf-8"))["tasks"]
    original = (campaign / "indexed/.aicontext/manifest.json").read_bytes()
    report = {
        "campaign": str(campaign),
        "scope": "offline integration, no provider billing",
        "budget": args.budget,
        "cli": [],
        "mcp": [],
        "hooks": [],
    }
    previous = dict(os.environ)
    scratch_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="prism-preflight-") as temp:
            scratch = Path(temp)
            scratch_path = scratch
            root = scratch / "repo"
            shutil.copytree(campaign / "indexed", root, ignore=ignore)
            env = dict(
                os.environ,
                PYTHONPATH=str(PRISM),
                PYTHONIOENCODING="utf-8",
                PYTHONUTF8="1",
                PRISM_CONFIG_HOME=str(scratch / "config"),
                PRISM_DAEMON="0",
            )
            os.environ.update(env)
            setup = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "prism",
                    "init",
                    "--root",
                    str(root),
                    "--agent",
                    "none",
                    "--no-hooks",
                    "--no-mcp",
                    "--no-git-hooks",
                    "--yes",
                    "--no-scan",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            if setup.returncode:
                raise RuntimeError(setup.stdout + setup.stderr)
            # A normal prism scan warms these caches. Recreate that preparation
            # explicitly after dropping the copied generation; do not hide it in CLI calls.
            started = time.perf_counter()
            warm_caches(root)
            report["cache_preparation"] = {
                "ready": caches_ready(root),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "reason": "rebuild disposable query caches as normal scan preparation",
            }
            for task in tasks:
                start = time.perf_counter()
                sid = "preflight-hook-" + task["id"]
                result = subprocess.run(
                    [sys.executable, "-X", "utf8", "-m", "prism", "hook", "user-prompt"],
                    input=json.dumps(
                        {"cwd": str(root), "session_id": sid, "prompt": "Task: " + task["request"]}
                    ),
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                )
                text = result.stdout
                logs = sessions(root)
                deliveries = [d for log in logs if log.digest == hashlib.sha256(sid.encode()).hexdigest()[:16] for d in log.deliveries if d[0] == "hook"]
                current = deliveries[0] if deliveries else ("hook", False, "no record")
                report["hooks"].append(
                    {
                        "task": task["id"],
                        "exit_code": result.returncode,
                        "delivered": current[1] and result.returncode == 0,
                        "reason": current[2],
                        "estimated_tokens": estimate_tokens(text),
                        "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                    }
                )
            for task in tasks:
                start = time.perf_counter()
                result = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-m",
                        "prism",
                        "task",
                        task["request"],
                        "--root",
                        str(root),
                        "--budget",
                        str(args.budget),
                        "--json",
                        "--session",
                        "preflight-cli-" + task["id"],
                    ],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=120,
                )
                pack = (
                    json.loads(result.stdout) if result.stdout.strip() else {"error": result.stderr}
                )
                report["cli"].append(
                    {
                        "task": task["id"],
                        "exit_code": result.returncode,
                        "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                        **summary(pack),
                    }
                )
            report["mcp"] = asyncio.run(mcp_queries(root, env, tasks, args.budget))
    except Exception as exc:
        report["fatal_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        os.environ.clear()
        os.environ.update(previous)
    report["sandbox_deleted"] = scratch_path is not None and not scratch_path.exists()
    report["campaign_manifest_unchanged"] = (
        hashlib.sha256(original).digest()
        == hashlib.sha256((campaign / "indexed/.aicontext/manifest.json").read_bytes()).digest()
    )
    report["healthy"] = (
        not report.get("fatal_error")
        and report["sandbox_deleted"]
        and report["campaign_manifest_unchanged"]
        and len(report["cli"]) == len(report["mcp"]) == len(tasks)
        and all(not r["error"] and r["exit_code"] == 0 and r["has_evidence"] for r in report["cli"])
        and all(
            not r["error"] and not r["transport_error"] and r["has_evidence"] for r in report["mcp"]
        )
        and (
            not args.require_hooks
            or (all(r["delivered"] for r in report["hooks"]) and len(report["hooks"]) == len(tasks))
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["healthy"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
