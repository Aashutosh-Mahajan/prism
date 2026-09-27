"""Token-savings harness (CLAUDE.md Section 18): orientation tokens with vs. without PRISM.

    python -m tests.benchmarks.tokens [--repo PATH ...] [--json]

Each task is a realistic request ("fix X") with the symbol a correct fix must touch. Two
agent strategies are replayed against the same repository copy and measured with PRISM's
documented tokenizer approximation (chars/4, `prism.core.tokens.estimate_tokens`):

Without PRISM (what agents do today, per CLAUDE.md Section 1):
  1. list the source files,
  2. grep the repository for the function name (generous: assumes the agent knows it),
  3. read whole files: the definition, every file that calls it, and its related tests.
  A "best case" variant reads only the defining file — a lower bound nobody hits in
  practice, reported so the savings are not overstated.

With PRISM (the prism-context skill):
  1. the session brief (AGENTS.md + freshness line),
  2. one `prism search` with the request text,
  3. one `prism context` pack for the target,
  4. only the line ranges in the pack's read list (measured from the real files).

Every repository is copied into a temporary directory with an isolated consent registry;
nothing in the source repository is initialised, scanned, or modified.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prism.core.tokens import estimate_tokens
from prism.extractors.toolchain import project_dirs
from prism.lifecycle import apply_init, plan_init, scan, update
from prism.navigator.api import op_brief, op_context, op_impact, op_search
from prism.navigator.render import render_brief, render_context, render_impact, render_search
from prism.navigator.store import IndexStore

REPO_ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "node_modules", "build", "dist", "*.egg-info", "__pycache__", ".*_cache",
    ".aicontext", ".test-build", "viewer_dist",
)  # fmt: skip


@dataclass(frozen=True)
class Task:
    request: str
    target: str


PRISM_TASKS = [
    Task("context pack goes over the token budget and drops the callers", "prism.navigator.context_pack.build_context"),
    Task("recording an audit finding twice creates a duplicate instead of deduping", "prism.audit.record.record_finding"),
    Task("drift score does not mark AGENTS.md sections stale after public signature changes", "prism.drift.scoring.apply_drift"),
    Task("pagerank importance scores do not converge on graphs with dangling nodes", "prism.graph.ranking.pagerank"),
    Task("hooks run in repos where the user never enabled prism consent", "prism.consent.registry.repo_state"),
    Task("nested gitignore negation patterns are ignored during file discovery", "prism.discovery.scanner.discover"),
    Task("post edit hook blocks the agent when the update is slow", "prism.hooks.runner.post_edit"),
    Task("refresh commit overwrites generated regions of AGENTS.md", "prism.narrator.refresh.refresh_commit"),
    Task("audit plan ranks low risk files above untested central code", "prism.audit.plan.build_plan"),
    Task("viewer server accepts requests without the session token", "prism.viewer.server.make_handler"),
]  # fmt: skip

SEEDED_TASKS = [
    Task("coupon discount is applied to the original price instead of the sale price", "ledger.pricing.apply_discount"),
    Task("finding entries is vulnerable to SQL injection", "ledger.storage.find_entries"),
    Task("report pagination skips the first page", "ledger.report.page"),
    Task("importing the feed silently swallows errors", "ledger.sync.import_feed"),
    Task("worker run once never actually runs the job", "ledger.worker.run_once"),
]  # fmt: skip


@dataclass
class TaskResult:
    request: str
    target: str
    without: int
    without_best_case: int
    with_prism: int
    search_rank: int | None  # 1-based rank of the target in the search results
    file_in_top3: bool  # a top-3 hit is in the target's file (the agent lands in the right place)
    caller_files: int
    caller_files_in_read_list: int
    detail: dict[str, int] = field(default_factory=dict)

    @property
    def saving(self) -> float:
        return 1 - self.with_prism / self.without if self.without else 0.0


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _grep(root: Path, files: list[str], word: str) -> str:
    """`grep -rn word` over the indexed source files, as `path:line:text` lines."""
    pattern = re.compile(rf"\b{re.escape(word)}\b")
    out = []
    for rel in files:
        for i, line in enumerate(_read(root, rel).splitlines(), 1):
            if pattern.search(line):
                out.append(f"{rel}:{i}:{line.strip()}")
    return "\n".join(out)


def _range(root: Path, rel: str, lines: list[int] | None) -> str:
    text = _read(root, rel)
    if not lines:
        return text
    return "\n".join(text.splitlines()[lines[0] - 1 : lines[1]])


def run_task(root: Path, store: IndexStore, files: list[str], task: Task) -> TaskResult:
    sym = store.symbol(task.target)
    if sym is None:
        raise SystemExit(f"task target {task.target} is not in the index")
    symbols = {s["id"]: s for s in _symbols(root)}
    entry = symbols[task.target]
    caller_files = sorted(
        {symbols[c]["file"] for c in entry["called_by"] if c in symbols} - {sym.file}
    )
    tests = sorted(set(_tests_for(root, task.target, sym.file)) - {sym.file, *caller_files})

    # Without PRISM
    listing = estimate_tokens("\n".join(files))
    name = task.target.rsplit(".", 1)[-1]
    grep = estimate_tokens(_grep(root, files, name))
    definition = estimate_tokens(_read(root, sym.file))
    callers = sum(estimate_tokens(_read(root, f)) for f in caller_files)
    test_tokens = sum(estimate_tokens(_read(root, f)) for f in tests)
    without = listing + grep + definition + callers + test_tokens
    best_case = listing + grep + definition

    # With PRISM
    brief = estimate_tokens(render_brief(op_brief(root)))
    found = op_search(store, task.request, limit=10)
    search = estimate_tokens(render_search(found))
    rank = next((i for i, h in enumerate(found["hits"], 1) if h["id"] == task.target), None)
    file_hit = any(h.get("file") == sym.file for h in found["hits"][:3])
    pack = op_context(store, task.target)
    context = estimate_tokens(render_context(pack))
    reads = sum(estimate_tokens(_range(root, r["file"], r.get("lines"))) for r in pack["read_list"])
    read_files = {r["file"] for r in pack["read_list"]}
    with_prism = brief + search + context + reads

    return TaskResult(
        request=task.request,
        target=task.target,
        without=without,
        without_best_case=best_case,
        with_prism=with_prism,
        search_rank=rank,
        file_in_top3=file_hit,
        caller_files=len(caller_files),
        caller_files_in_read_list=len(read_files & set(caller_files)),
        detail={
            "listing": listing,
            "grep": grep,
            "definition_file": definition,
            "caller_files": callers,
            "test_files": test_tokens,
            "brief": brief,
            "search": search,
            "context_pack": context,
            "targeted_reads": reads,
        },
    )


_SYMBOL_CACHE: dict[Path, list[dict[str, Any]]] = {}


def _symbols(root: Path) -> list[dict[str, Any]]:
    if root not in _SYMBOL_CACHE:
        doc = json.loads((root / ".aicontext" / "symbols.json").read_text(encoding="utf-8"))
        _SYMBOL_CACHE[root] = doc["symbols"]
    return _SYMBOL_CACHE[root]


def _tests_for(root: Path, symbol: str, file: str) -> list[str]:
    doc = json.loads((root / ".aicontext" / "tests_map.json").read_text(encoding="utf-8"))
    return [*doc.get("by_symbol", {}).get(symbol, []), *doc.get("by_file", {}).get(file, [])]


MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "setup.cfg")


def workflow(root: Path, store: IndexStore, files: list[str], tasks: list[Task]) -> dict[str, Any]:
    """Session-level costs around the per-task numbers.

    Orientation (once per session) without PRISM is a conservative floor: the file list,
    the README, and each app's dependency manifest, which is how an agent learns the stack
    and the test command. With PRISM it is the injected brief. Before editing, PRISM's
    `impact` names the dependents and the tests to run; without it the agent has no
    targeted test list and runs every test file.
    """
    readme = sum(
        estimate_tokens(_read(root, p.name)) for p in sorted(root.glob("README*")) if p.is_file()
    )
    manifests = sum(
        estimate_tokens(_read(root, f"{d}/{m}" if d else m))
        for d in project_dirs(root)
        for m in MANIFESTS
    )
    listing = estimate_tokens("\n".join(files))
    brief = estimate_tokens(render_brief(op_brief(root)))
    test_files = json.loads((root / ".aicontext" / "tests_map.json").read_text(encoding="utf-8"))[
        "test_files"
    ]
    impact_tokens: list[int] = []
    targeted: list[int] = []
    for task in tasks:
        data = op_impact(store, task.target)
        impact_tokens.append(estimate_tokens(render_impact(data)))
        targeted.append(len(data["tests"]))
    return {
        "orientation_without": listing + readme + manifests,
        "orientation_with": brief,
        "impact_tokens_avg": round(sum(impact_tokens) / len(impact_tokens)),
        "test_files_total": len(test_files),
        "tests_targeted_avg": round(sum(targeted) / len(targeted), 1),
        "tasks_with_mapped_tests": sum(1 for n in targeted if n),
    }


def edit_loop(root: Path, tasks: list[Task]) -> dict[str, Any]:
    """Edit each target's file the way an agent would (a line inserted above the target),
    run the post-edit update, and check the index moved the target to its new lines."""
    times: list[float] = []
    correct = 0
    for task in tasks:
        store = IndexStore.open(root)
        try:
            before = store.symbol(task.target)
        finally:
            store.close()
        assert before is not None
        path = root / before.file
        comment = "# edited" if before.file.endswith(".py") else "// edited"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        target_line = lines[before.start - 1]
        indent = target_line[: len(target_line) - len(target_line.lstrip())]
        lines.insert(before.start - 1, f"{indent}{comment}\n")
        path.write_text("".join(lines), encoding="utf-8")
        start = time.perf_counter()
        update(root, files=[before.file])
        times.append(time.perf_counter() - start)
        store = IndexStore.open(root)
        try:
            after = store.symbol(task.target)
        finally:
            store.close()
        if after and (after.start, after.end) == (before.start + 1, before.end + 1):
            correct += 1
    times.sort()
    return {
        "update_seconds_p50": round(times[len(times) // 2], 3),
        "update_seconds_max": round(times[-1], 3),
        "index_correct_after_edit": correct,
        "edits": len(tasks),
    }


def benchmark_repo(source: Path, tasks: list[Task]) -> dict[str, Any]:
    previous = os.environ.get("PRISM_CONFIG_HOME")
    with tempfile.TemporaryDirectory(prefix="prism-tokens-") as temp:
        base = Path(temp)
        os.environ["PRISM_CONFIG_HOME"] = str(base / "config")
        try:
            root = base / source.name
            shutil.copytree(source, root, ignore=COPY_IGNORE)
            apply_init(plan_init(root))
            manifest = scan(root)
            files = sorted(manifest["files"])
            loc = sum(len(_read(root, f).splitlines()) for f in files)
            store = IndexStore.open(root)
            try:
                results = [run_task(root, store, files, t) for t in tasks]
                flow = workflow(root, store, files, tasks)
            finally:
                store.close()
            flow.update(edit_loop(root, tasks))
            _SYMBOL_CACHE.pop(root, None)
        finally:
            if previous is None:
                os.environ.pop("PRISM_CONFIG_HOME", None)
            else:
                os.environ["PRISM_CONFIG_HOME"] = previous
    total_without = sum(r.without for r in results)
    total_best = sum(r.without_best_case for r in results)
    total_with = sum(r.with_prism for r in results)
    return {
        "repo": source.name,
        "files": len(files),
        "loc": loc,
        "tasks": [asdict(r) | {"saving": round(r.saving, 3)} for r in results],
        "total_without": total_without,
        "total_without_best_case": total_best,
        "total_with_prism": total_with,
        "saving": round(1 - total_with / total_without, 3),
        "saving_vs_best_case": round(1 - total_with / total_best, 3),
        "search_top3": sum(1 for r in results if r.search_rank and r.search_rank <= 3),
        "file_top3": sum(1 for r in results if r.file_in_top3),
        "tasks_run": len(results),
        "workflow": flow,
    }


def _print(report: dict[str, Any]) -> None:
    print(f"\n## {report['repo']} - {report['files']} files, {report['loc']:,} lines")
    print(f"{'task target':<48} {'without':>8} {'with':>7} {'saved':>6}  search  callers")
    for t in report["tasks"]:
        rank = f"#{t['search_rank']}" if t["search_rank"] else "miss"
        callers = f"{t['caller_files_in_read_list']}/{t['caller_files']}"
        print(
            f"{t['target'][-48:]:<48} {t['without']:>8,} {t['with_prism']:>7,} "
            f"{t['saving']:>6.0%}  {rank:>6}  {callers:>7}"
        )
    print(
        f"{'TOTAL':<48} {report['total_without']:>8,} {report['total_with_prism']:>7,} "
        f"{report['saving']:>6.0%}"
    )
    w = report["workflow"]
    n = report["tasks_run"]
    session_without = w["orientation_without"] + report["total_without"]
    session_with = w["orientation_with"] + report["total_with_prism"] + w["impact_tokens_avg"] * n
    impact_total = w["impact_tokens_avg"] * n
    rows = [
        f"\nWorkflow ({n}-task session):",
        f"  project orientation     without {w['orientation_without']:>8,}"
        f"   with {w['orientation_with']:>6,} (brief)",
        f"  find + understand code  without {report['total_without']:>8,}"
        f"   with {report['total_with_prism']:>6,}",
        f"  pre-edit impact check   without {'n/a':>8}   with {impact_total:>6,}"
        " (names dependents + tests)",
        f"  SESSION TOTAL           without {session_without:>8,}   with {session_with:>6,}"
        f"   saved {1 - session_with / session_without:.0%}",
        f"  tests to run per edit: {w['tests_targeted_avg']} targeted vs"
        f" {w['test_files_total']} test files (mapped for {w['tasks_with_mapped_tests']}/{n} targets)",
        f"  after each edit: index update p50 {w['update_seconds_p50']}s,"
        f" max {w['update_seconds_max']}s; target found at its new lines"
        f" {w['index_correct_after_edit']}/{w['edits']}",
    ]
    print("\n".join(rows))
    print(
        f"vs. best-case baseline (definition file only): {report['total_without_best_case']:,} "
        f"-> {report['saving_vs_best_case']:.0%} saved; search found the target in the top 3 "
        f"for {report['search_top3']}/{report['tasks_run']} requests "
        f"(right file in the top 3: {report['file_top3']}/{report['tasks_run']})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--repo", type=Path, help="benchmark another repository (copied, never modified)"
    )
    parser.add_argument(
        "--tasks", type=Path, help='JSON list of {"request": ..., "target": <symbol id>} for --repo'
    )
    args = parser.parse_args()
    if args.repo:
        if not args.tasks:
            parser.error("--repo needs --tasks")
        raw = json.loads(args.tasks.read_text(encoding="utf-8"))
        reports = [benchmark_repo(args.repo, [Task(t["request"], t["target"]) for t in raw])]
    else:
        reports = [
            benchmark_repo(REPO_ROOT, PRISM_TASKS),
            benchmark_repo(REPO_ROOT / "tests" / "fixtures" / "repos" / "seeded", SEEDED_TASKS),
        ]
    if args.json:
        print(json.dumps(reports, indent=2))
        return
    for report in reports:
        _print(report)


if __name__ == "__main__":
    main()
