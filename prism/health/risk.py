"""Per-file and per-symbol risk = f(complexity, churn, coverage, centrality, findings).

Scores are in [0, 1] and every score carries human-readable reasons so an
agent (or person) can see why something is flagged.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from prism.core.models import GitIntel, Health, ParsedFile, Smell, Symbol

HIGH_COMPLEXITY = 10
VERY_HIGH_COMPLEXITY = 20
W_COMPLEXITY, W_CHURN, W_COVERAGE, W_CENTRALITY = 0.3, 0.25, 0.25, 0.2
FINDING_BONUS = 0.15


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _innermost(symbols: list[Symbol], line: int) -> str | None:
    best: Symbol | None = None
    for s in symbols:
        if s.lines[0] <= line <= s.lines[1] and (
            best is None or s.lines[1] - s.lines[0] < best.lines[1] - best.lines[0]
        ):
            best = s
    return best.id if best else None


def compute_health(
    parsed: Iterable[ParsedFile],
    symbols: dict[str, Symbol],
    complexity: dict[str, int],
    module_rank: dict[str, float],
    tested_files: set[str],
    tested_symbols: set[str],
    git: GitIntel | None,
    coverage: dict[str, float],
    open_findings: dict[str, int],
    test_files: set[str],
) -> Health:
    by_file: dict[str, list[Symbol]] = {}
    for s in symbols.values():
        by_file.setdefault(s.file, []).append(s)
    churn = git.churn if git and git.available else {}
    max_churn = max(churn.values(), default=0) or 1
    ranks = sorted(module_rank.values())
    max_rank = ranks[-1] if ranks else 1.0
    top_decile = ranks[int(len(ranks) * 0.9)] if len(ranks) >= 10 else max_rank
    max_sym_rank = max((s.rank for s in symbols.values()), default=0.0) or 1.0

    files: dict[str, dict[str, Any]] = {}
    for pf in sorted(parsed, key=lambda p: p.path):
        if pf.parse_error or pf.language != "python":
            continue
        path = pf.path
        syms = by_file.get(path, [])
        cx = max((complexity.get(s.id, 1) for s in syms), default=1)
        total_cx = sum(complexity.get(s.id, 1) for s in syms if s.kind != "class")
        reasons: list[str] = []
        c_score = _clamp((cx - 1) / VERY_HIGH_COMPLEXITY)
        if cx >= HIGH_COMPLEXITY:
            worst = max(syms, key=lambda s: complexity.get(s.id, 1))
            reasons.append(f"high complexity (cc {cx} in {worst.name})")
        ch = churn.get(path, 0)
        ch_score = ch / max_churn if churn else 0.0
        if churn and ch_score >= 0.5 and ch >= 3:
            reasons.append(f"high churn ({ch} commits)")
        cov = coverage.get(path)
        if cov is not None:
            cov_gap = 1.0 - cov
            if cov < 0.5:
                reasons.append(f"low coverage ({round(cov * 100)}%)")
        elif path in test_files:
            cov_gap = 0.0
        else:
            cov_gap = 0.2 if path in tested_files else 0.6
            if path not in tested_files and syms:
                reasons.append("no mapped tests")
        rank = module_rank.get(pf.module, 0.0)
        cen = rank / max_rank if max_rank else 0.0
        if len(ranks) >= 10 and rank >= top_decile and rank > 0:
            reasons.append("central module (top 10% by importance)")
        n_findings = open_findings.get(path, 0)
        if n_findings:
            reasons.append(f"{n_findings} open audit finding{'s' if n_findings > 1 else ''}")
        risk = _clamp(
            W_COMPLEXITY * c_score
            + W_CHURN * ch_score
            + W_COVERAGE * cov_gap
            + W_CENTRALITY * cen
            + FINDING_BONUS * n_findings
        )
        smells: list[dict[str, Any]] = [
            {"kind": s.kind, "line": s.line, "detail": s.detail, "symbol": _innermost(syms, s.line)}
            for s in pf.smells
        ]
        entry: dict[str, Any] = {
            "complexity": {"max": cx, "total": total_cx},
            "churn": ch,
            "coverage": cov,
            "centrality": round(cen, 3),
            "risk": round(risk, 3),
            "reasons": reasons,
            "smells": smells,
        }
        if git and git.available and path in git.owners:
            entry["owners"] = [name for name, _ in git.owners[path]]
        files[path] = entry

    symbol_health: dict[str, dict[str, Any]] = {}
    for sid, s in sorted(symbols.items()):
        if s.kind == "class" or s.file in test_files or s.file not in files:
            continue
        cx = complexity.get(sid, 1)
        reasons = []
        if cx >= HIGH_COMPLEXITY:
            reasons.append(f"high complexity (cc {cx})")
        tested = sid in tested_symbols
        if not tested and s.visibility == "public" and s.called_by:
            reasons.append("no direct test coverage")
        fh = files[s.file]
        if fh["churn"] and "high churn" in " ".join(fh["reasons"]):
            reasons.append(f"file has high churn ({fh['churn']} commits)")
        centrality = s.rank / max_sym_rank
        if centrality >= 0.5:
            reasons.append("widely used")
        n_findings = open_findings.get(sid, 0)
        if n_findings:
            reasons.append(f"{n_findings} open audit finding{'s' if n_findings > 1 else ''}")
        cov = fh["coverage"]
        cov_gap = (1.0 - cov) if isinstance(cov, float) else (0.2 if tested else 0.6)
        ch_score = (fh["churn"] / max_churn) if churn else 0.0
        risk = _clamp(
            W_COMPLEXITY * _clamp((cx - 1) / VERY_HIGH_COMPLEXITY)
            + W_CHURN * ch_score
            + W_COVERAGE * cov_gap
            + W_CENTRALITY * centrality
            + FINDING_BONUS * n_findings
        )
        symbol_health[sid] = {"complexity": cx, "risk": round(risk, 3), "reasons": reasons}
    return Health(files=files, symbols=symbol_health)


def smells_by_kind(health: Health) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in health.files.values():
        for smell in entry.get("smells", []):  # type: ignore[attr-defined]
            counts[smell["kind"]] = counts.get(smell["kind"], 0) + 1
    return dict(sorted(counts.items()))


__all__ = ["Smell", "compute_health", "smells_by_kind"]
