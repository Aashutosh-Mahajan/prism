"""A bounded inspection of the persistent project knowledge, not a source dump."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.navigator.store import IndexStore


def render_knowledge(packet: dict[str, Any]) -> str:
    counts = packet["counts"]
    return "\n".join(
        [
            f"PRISM local knowledge · {counts['files']} files · {counts['symbols']} symbols",
            f"Relationships: {counts['calls']} calls, {counts['imports']} imports",
            "Languages: "
            + ", ".join(f"{name} ({count})" for name, count in packet["languages"].items()),
            "Modules: " + ", ".join(packet["modules"]),
            "Storage: .aicontext/ (portable facts, narratives and local query caches)",
            'Retrieve only the task working set: prism task "<request>".',
        ]
    )


def knowledge(store: IndexStore, budget: int = 600) -> dict[str, Any]:
    if not 128 <= budget <= 32000:
        raise UserError("knowledge budget must be between 128 and 32000")
    languages = Counter(
        str(f.get("language", "unknown")) for f in store.manifest.get("files", {}).values()
    )
    counts = {
        name: int(store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for name, table in (
            ("files", "files"),
            ("symbols", "symbols"),
            ("calls", "calls"),
            ("imports", "imports"),
        )
    }
    packet: dict[str, Any] = {
        "schema_version": 1,
        "counts": counts,
        "languages": dict(sorted(languages.items())),
        "modules": [],
        "budget": {"requested": budget, "used_est": 0, "estimator": "ceil(chars/4)"},
    }

    def size() -> int:
        packet["budget"]["used_est"] = 99999
        return max(
            estimate_tokens(json.dumps(packet, indent=2)), estimate_tokens(render_knowledge(packet))
        )

    for module in store.conn.execute("SELECT id FROM modules ORDER BY rank DESC, id LIMIT 8"):
        packet["modules"].append(module[0])
        if size() > budget:
            packet["modules"].pop()
            break
    while size() > budget and packet["languages"]:
        packet["languages"].popitem()
    packet["budget"]["used_est"] = size()
    return packet
