"""Git intelligence: churn, ownership, recency, and co-change pairs from `git log`.

Uses the `git` CLI (no GitPython). Optional: without git or history, returns
`available=False` and every consumer degrades gracefully.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from itertools import combinations
from pathlib import Path

from prism.core.models import GitIntel

MAX_COMMITS = 1000
MAX_FILES_PER_COMMIT = 30  # bulk commits (renames, formatting) say little about coupling
MIN_PAIR_COUNT = 2
PAIRS_PER_FILE = 5
TIMEOUT = 15


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def git_head(root: Path) -> str | None:
    head = _git(root, "rev-parse", "HEAD")
    return head.strip() if head else None


def collect_git(root: Path, indexed: set[str], previous: GitIntel | None = None) -> GitIntel:
    head = git_head(root)
    if head is None:
        return GitIntel(available=False)
    if previous is not None and previous.available and previous.head == head:
        return previous  # history unchanged since the last run
    log = _git(
        root,
        "log",
        "--no-merges",
        "--relative",
        f"-n{MAX_COMMITS}",
        "--name-only",
        "--format=%x1e%H%x1f%an%x1f%ct",
    )
    if log is None:
        return GitIntel(available=False)

    churn: Counter[str] = Counter()
    authors: dict[str, Counter[str]] = {}
    last: dict[str, int] = {}
    pairs: Counter[tuple[str, str]] = Counter()
    commits = 0
    for record in log.split("\x1e"):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        parts = header.split("\x1f")
        if len(parts) != 3:
            continue
        commits += 1
        _, author, ts = parts
        files = sorted({f.strip() for f in body.splitlines() if f.strip() in indexed})
        for f in files:
            churn[f] += 1
            authors.setdefault(f, Counter())[author] += 1
            last[f] = max(last.get(f, 0), int(ts))
        if 2 <= len(files) <= MAX_FILES_PER_COMMIT:
            pairs.update(combinations(files, 2))

    scored: list[tuple[str, str, int, float]] = []
    for (a, b), n in pairs.items():
        if n < MIN_PAIR_COUNT:
            continue
        jaccard = n / (churn[a] + churn[b] - n)
        scored.append((a, b, n, round(jaccard, 3)))
    # Keep each file's strongest partners only.
    keep: set[tuple[str, str]] = set()
    per_file: dict[str, list[tuple[str, str, int, float]]] = {}
    for pair in scored:
        per_file.setdefault(pair[0], []).append(pair)
        per_file.setdefault(pair[1], []).append(pair)
    for items in per_file.values():
        for pair in sorted(items, key=lambda p: (-p[3], -p[2], p[0], p[1]))[:PAIRS_PER_FILE]:
            keep.add((pair[0], pair[1]))
    co_change = sorted((p for p in scored if (p[0], p[1]) in keep), key=lambda p: (p[0], p[1]))
    owners = {
        f: sorted(c.items(), key=lambda x: (-x[1], x[0]))[:3] for f, c in sorted(authors.items())
    }
    return GitIntel(
        available=True,
        head=head,
        commits_analyzed=commits,
        churn=dict(sorted(churn.items())),
        owners=owners,
        last_changed=dict(sorted(last.items())),
        co_change=co_change,
    )
