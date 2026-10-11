"""Opt-in local query diagnostics; no query text, source, network, or billing claims."""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class Measurement:
    counters: dict[str, int] = field(default_factory=dict)
    stages_ms: dict[str, float] = field(default_factory=dict)


_ACTIVE: ContextVar[Measurement | None] = ContextVar("prism_query_metrics", default=None)


def count(name: str, value: int = 1) -> None:
    active = _ACTIVE.get()
    if active is not None:
        active.counters[name] = active.counters.get(name, 0) + value


@contextlib.contextmanager
def stage(name: str) -> Iterator[None]:
    active = _ACTIVE.get()
    if active is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        active.stages_ms[name] = (
            active.stages_ms.get(name, 0) + (time.perf_counter() - start) * 1000
        )


def profile_task(fn: F) -> F:
    @functools.wraps(fn)
    def measured(*args: Any, **kwargs: Any) -> Any:
        if os.environ.get("PRISM_PROFILE") != "1" or _ACTIVE.get() is not None:
            return fn(*args, **kwargs)
        measurement = Measurement()
        token = _ACTIVE.set(measurement)
        start = time.perf_counter()
        result: dict[str, Any] | None = None
        try:
            result = fn(*args, **kwargs)
            return result
        finally:
            _ACTIVE.reset(token)
            store = args[0] if args else kwargs["store"]
            query = args[1] if len(args) > 1 else kwargs.get("query", "")
            row = {
                "scope": "navigator only; excludes launcher/freshness and billing",
                "query_hash": hashlib.sha256(str(query).encode()).hexdigest()[:16],
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                "stages_ms": {k: round(v, 3) for k, v in measurement.stages_ms.items()},
                "counters": measurement.counters,
                "success": result is not None,
                "estimated_packet_tokens": (result or {}).get("budget", {}).get("used_est"),
            }
            _save(store.root, row)

    return cast(F, measured)


def _save(root: Path, row: dict[str, Any]) -> None:
    from prism.consent import cache_root

    path = cache_root(root) / "query-metrics.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        if path.stat().st_size > 1024 * 1024:
            from prism.writers.json_writer import write_text

            write_text(path, "\n".join(path.read_text(encoding="utf-8").splitlines()[-256:]) + "\n")
    except OSError:
        pass
