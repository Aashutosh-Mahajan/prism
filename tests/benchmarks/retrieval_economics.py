"""Deterministic retrieval diagnostic; never represents full-agent token savings.

Run with an already indexed Plexus checkout and an output JSON path.
The gold targets are frozen before changing retrieval code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from prism.navigator.api import op_task
from prism.navigator.store import IndexStore

CASES = (
    (
        "github specification",
        "Fix extraction of the owner/repository slug used by GitHub pull-request creation. Accept only HTTP/HTTPS URLs with github.com as the actual host, git@github.com:owner/repo SCP syntax, or ssh://git@github.com/owner/repo. Host matching is case-insensitive. Strip surrounding whitespace, trailing slashes and one optional .git suffix; preserve owner/repo spelling. Reject foreign/lookalike hosts, unsupported schemes, HTTP credentials, any explicit port, query strings, fragments, extra path components and bare local paths with ValueError.",
        "._parse_repo_slug",
    ),
    (
        "github paraphrase",
        "Fix parsing of GitHub repository addresses into owner and repo names. Reject other hosts with ValueError, but keep SSH and HTTPS clone addresses working.",
        "._parse_repo_slug",
    ),
    ("github short", "Fix the GitHub repo slug parser", "._parse_repo_slug"),
    (
        "severity specification",
        "Fix the final finding aggregation order when severity labels contain whitespace, mixed case, or code-review aliases. Normalize string labels with strip and case folding: critical=0, high=1, medium=2, low=3, info=4; error is an alias for high and warning is an alias for medium. Unknown labels, empty strings and null rank last at 5. Preserve severity-first then descending-confidence ordering and stable ties.",
        "._severity_rank",
    ),
    (
        "severity paraphrase",
        "Fix severity ranking for findings. Allow warning and error aliases and labels padded with whitespace; leave confidence and deduplication alone.",
        "._severity_rank",
    ),
    ("severity short", "Fix severity sorting", "._severity_rank"),
    (
        "privacy specification",
        "Fix AWS-secret handling in the privacy routing feature. For each candidate matching the existing 40-character AWS secret-key regex, treat it as sensitive only if aws, secret, credentials or access appears within the 80 characters immediately before or after that candidate. Detection, masking and routing must agree. Mask only sensitive candidates with [MASKED_AWS_SECRET_KEY]; preserve unrelated hashes when keywords occur farther away.",
        ".contains_sensitive_data",
    ),
    (
        "privacy paraphrase",
        "Fix privacy sensitive-data detection and masking so hashes far from an AWS keyword stay unchanged",
        ".contains_sensitive_data",
    ),
    ("privacy short", "Fix AWS secret detection", ".contains_sensitive_data"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    store = IndexStore.open(args.root)
    rows = []
    try:
        for name, query, target in CASES:
            pack = op_task(store, query, 1169)
            blocks = pack["blocks"]
            covered = [
                b
                for b in blocks
                if target in (b["symbol"] or "") or f"def {target[1:]}(" in b.get("source", "")
            ]
            rows.append(
                {
                    "case": name,
                    "query": query,
                    "target": target,
                    "first_target": bool(
                        blocks
                        and (
                            target in (blocks[0]["symbol"] or "")
                            or f"def {target[1:]}(" in blocks[0].get("source", "")
                        )
                    ),
                    "complete_target": any(
                        f"def {target[1:]}(" in b.get("source", "") and not b["truncated"]
                        for b in covered
                    ),
                    "confidence": pack["confidence"],
                    "sufficient": pack["sufficient"],
                    "packet_tokens_est": pack["budget"]["used_est"],
                    "symbols": [b["symbol"] for b in blocks],
                }
            )
    finally:
        store.close()
    result = {
        "type": "static retrieval diagnostic, not measured agent savings",
        "gold_frozen": True,
        "rows": rows,
        "first_targets": sum(r["first_target"] for r in rows),
        "complete_targets": sum(r["complete_target"] for r in rows),
        "cases": len(rows),
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
