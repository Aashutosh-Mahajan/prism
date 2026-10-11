"""Offline parent-commit replay: python -m tests.benchmarks.replay_precision.

The current engine queries isolated historical worktrees, never the live index.
Commit subjects are a retrieval proxy, not a measurement of agent savings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task

ROOT = Path(__file__).resolve().parents[2]
HEADER = re.compile(r"^([^:\n]+): (.+?):(\d+)(?:-(\d+))?(?: .*)?$")
NUMBER = re.compile(r"^(\d+): ?")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


@dataclass(frozen=True)
class SourceBlock:
    file: str
    start: int
    end: int
    source: str
    delivered_lines: frozenset[int]


def parse_packet(text: str) -> list[SourceBlock]:
    """Only fenced source following a source header counts as delivered code."""
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        match = HEADER.match(lines[i])
        if not match or i + 1 == len(lines) or not re.fullmatch(r"`{3,}", lines[i + 1]):
            i += 1
            continue
        start = int(match[3])
        end = int(match[4] or match[3])
        body: list[str] = []
        delivered: set[int] = set()
        cursor = start
        fence = lines[i + 1]
        i += 2
        while i < len(lines) and lines[i] != fence:
            line = lines[i]
            numbered = NUMBER.match(line)
            if numbered:
                cursor = int(numbered[1])
                delivered.add(cursor)
                body.append(line[numbered.end() :])
                cursor += 1
            elif omitted := re.match(r"^⋮ (\d+) lines omitted", line):
                cursor += int(omitted[1])
            else:
                delivered.add(cursor)
                body.append(line)
                cursor += 1
            i += 1
        if i == len(lines):
            raise ValueError("unterminated source fence")
        blocks.append(SourceBlock(match[2], start, end, "\n".join(body), frozenset(delivered)))
        i += 1
    return blocks


def parse_hunks(diff: str) -> list[tuple[str, int, int]]:
    """Old-side changed ranges. Pure insertions use the preceding parent line.

    New files have no parent source and are excluded from hunk recall, but remain
    misses in file recall. Deleted files remain measurable against their parent.
    """
    file = None
    hunks = []
    for line in diff.splitlines():
        if line.startswith("--- "):
            file = line[6:] if line.startswith("--- a/") else None
        elif file is not None and (match := HUNK.match(line)):
            start, count = int(match[1]), int(match[2] or "1")
            if count:
                hunks.append((file, start, start + count - 1))
            elif start:
                hunks.append((file, start, start))
    return hunks


def score_packet(text: str, gold: list[str], hunks: list[tuple[str, int, int]]) -> dict[str, Any]:
    blocks = parse_packet(text)
    found = {b.file for b in blocks} & set(gold)
    delivered: dict[str, set[int]] = {}
    for block in blocks:
        delivered.setdefault(block.file, set()).update(block.delivered_lines)
    relevant = [h for h in hunks if h[0] in gold]
    return {
        "expected_files": len(gold),
        "found_files": len(found),
        "any_hit": bool(found),
        "code_tokens": sum(estimate_tokens(b.source) for b in blocks),
        "useful_code_tokens": sum(estimate_tokens(b.source) for b in blocks if b.file in gold),
        "expected_hunks": len(relevant),
        "found_hunks": sum(
            set(range(start, end + 1)) <= delivered.get(file, set())
            for file, start, end in relevant
        ),
        "packet_tokens": estimate_tokens(text),
        "missing_files": sorted(set(gold) - found),
    }


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def provenance(root: Path, ref: str = "HEAD") -> dict[str, Any]:
    files = sorted((ROOT / "prism").rglob("*.py"))
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(ROOT).as_posix().encode())
        digest.update(file.read_bytes())
    return {
        "source_head": git(root, "rev-parse", ref),
        "engine_head": git(ROOT, "rev-parse", "HEAD"),
        "engine_python_sha256": digest.hexdigest(),
        "engine_dirty": bool(git(ROOT, "status", "--porcelain", "--", "prism")),
        "budget": 2000,
        "semantic": False,
        "estimator": "ceil(characters / 4)",
    }


@contextmanager
def isolated_environment(base: Path) -> Iterator[None]:
    values = {"PRISM_CONFIG_HOME": str(base / "config"), "PRISM_SEMANTIC": "0", "PRISM_DAEMON": "0"}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def historical_store(repo: Path, base: Path, revision: str) -> Iterator[IndexStore]:
    worktree = (base / "source").resolve()
    if not worktree.is_relative_to(base.resolve()):
        raise ValueError("scratch worktree must stay inside the temporary directory")
    git(repo, "worktree", "add", "--detach", str(worktree), revision)
    try:
        apply_init(plan_init(worktree))
        scan(worktree, warm=False)
        store = IndexStore.open(worktree)
        try:
            yield store
        finally:
            store.close()
    finally:
        # Only this verified, newly created scratch checkout is removed.
        git(repo, "worktree", "remove", "--force", str(worktree))


def select_commits(repo: Path, limit: int, history: int, ref: str = "HEAD") -> list[dict[str, Any]]:
    rows = []
    log = git(repo, "log", "--no-merges", "--format=%H%x09%s", "-n", str(history), ref)
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        if re.match(r"^(docs|chore|ci|test)(?:\(|!?:)", subject):
            continue
        query = re.sub(r"^\w+(\([^)]*\))?!?:\s*", "", subject)
        if len(query.split()) < 4:
            continue
        parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()
        if len(parents) != 2:
            continue
        files = git(repo, "diff", "--name-only", "--no-renames", parents[1], sha).splitlines()
        gold = [f for f in files if f.startswith("prism/") and f.endswith(".py")]
        if 1 <= len(gold) <= 4:
            parent_files = set(
                git(repo, "ls-tree", "-r", "--name-only", parents[1], "--", "prism").splitlines()
            )
            rows.append(
                {
                    "sha": sha,
                    "parent": parents[1],
                    "query": query,
                    "gold": gold,
                    "parent_missing_files": sorted(set(gold) - parent_files),
                }
            )
        if len(rows) == limit:
            break
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("no usable commits in the requested history")

    def total(key: str) -> int:
        return sum(row[key] for row in rows)

    missing = sum(len(row.get("parent_missing_files", [])) for row in rows)
    existing = total("expected_files") - missing
    return {
        "queries": len(rows),
        "file_recall_pct": 100 * total("found_files") / total("expected_files"),
        "any_hit_pct": 100 * total("any_hit") / len(rows),
        "token_precision_pct": 100 * total("useful_code_tokens") / max(1, total("code_tokens")),
        "block_recall_pct": 100 * total("found_hunks") / max(1, total("expected_hunks")),
        "scorable_hunks": total("expected_hunks"),
        "mean_packet_tokens": total("packet_tokens") / len(rows),
        "new_file_targets": missing,
        "all_new_commits": sum(
            bool(row.get("parent_missing_files"))
            and len(row["parent_missing_files"]) == row["expected_files"]
            for row in rows
        ),
        "existing_file_recall_pct": 100 * total("found_files") / existing if existing else None,
    }


def replay(repo: Path, limit: int, history: int, ref: str = "HEAD") -> dict[str, Any]:
    start = time.perf_counter()
    metadata = provenance(repo, ref)
    commits = select_commits(repo, limit, history, metadata["source_head"])
    rows = []
    with tempfile.TemporaryDirectory(prefix="prism-replay-") as temp:
        base = Path(temp)
        with isolated_environment(base):
            for i, commit in enumerate(commits):
                print(f"Replay {i + 1}/{len(commits)} {commit['sha'][:8]}", flush=True)
                diff = git(
                    repo,
                    "diff",
                    "--no-renames",
                    "--unified=0",
                    commit["parent"],
                    commit["sha"],
                    "--",
                    "prism",
                )
                with historical_store(repo, base, commit["parent"]) as store:
                    text = render_task(op_task(store, commit["query"], 2000, use_cache=False))
                rows.append(
                    {
                        **commit,
                        "packet": text,
                        "hunks": parse_hunks(diff),
                        **score_packet(text, commit["gold"], parse_hunks(diff)),
                    }
                )
    return {
        **metadata,
        "index_revision": "each commit's first parent",
        "rows": rows,
        "summary": summarise(rows),
        "elapsed_seconds": time.perf_counter() - start,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--commits", type=int, default=40)
    parser.add_argument("--history", type=int, default=150)
    parser.add_argument(
        "--ref", default="HEAD", help="Pin the source history for before/after comparisons."
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "output/benchmarks/replay_precision.json"
    )
    args = parser.parse_args()
    if min(args.commits, args.history) < 1:
        parser.error("commits and history must be positive")
    report = replay(args.repo.resolve(), args.commits, args.history, args.ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
