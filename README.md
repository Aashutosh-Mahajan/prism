# PRISM

**A persistent, local context layer for AI coding agents.**

PRISM maps a codebase once, keeps that map fresh as the code changes, and lets any coding agent
(Claude Code, Cursor, Codex, …) jump straight to the files, functions, and line ranges a task
touches, instead of re-reading the repository at the start of every session.

- Local and offline: no network calls, no API keys, no telemetry.
- Deterministic: the same code always produces the same `.aicontext/` bytes.
- Opt-in per project and per user: installing PRISM changes nothing until you run `prism init`.

> Status: **Index, navigation, freshness, auditing, and the graph viewer are implemented;
> Phase 5 is partial.** Optional parsers, agent adapters, local semantic search, communities,
> decisions, watch, and doctor exist. Optional 3D and VS Code webview support remain pending.
> See [phase status](docs/phase-status.md) for verified coverage and remaining work, and
> [CLAUDE.md](CLAUDE.md) for the product specification.

## Quick start

```bash
pip install prism-ctx
cd your-repo
prism init      # shows every change it will make and asks first
prism status
```

`prism init` creates `.aicontext/`, adds two cache paths to `.gitignore`, and records a local,
per-user enable flag in `~/.config/prism/repos.toml` (override with `PRISM_CONFIG_HOME`). It then
offers to run the first scan.

## What the index contains

| File | Contents |
|---|---|
| `AGENTS.md` | ≤ 600-token session brief: generated facts plus agent-written narrative sections |
| `symbols.json` | Every function, class, and method: file, lines, signature, doc, callers, callees, PageRank |
| `dependency_graph.json` | Module import graph, external dependencies, entry points, PageRank |
| `call_graph.json` | Symbol call graph with resolution confidence (`high` / `medium` / `low`) |
| `tests_map.json` | Symbol and file → related test files |
| `manifest.json` | Versions, per-file SHA-256, artifact hashes, scan timestamps |

## Configuration (optional)

In `pyproject.toml` under `[tool.prism]`, or in a `prism.toml`:

```toml
ignore = ["generated/", "*.pb.py"]   # gitignore syntax, on top of .gitignore and .prismignore
max_file_size = 1000000              # bytes
source_roots = ["src"]               # stripped when deriving module names
test_dirs = ["tests", "test"]
```

## Development

```bash
pip install -e ".[dev]"
ruff check prism tests && ruff format --check prism tests
mypy
pytest                                  # sockets are blocked for the whole suite
PRISM_UPDATE_GOLDEN=1 pytest -k golden  # refresh golden files after an intended output change
```

The graph viewer ships prebuilt; end users do not need Node. Frontend development uses Node 24:

```bash
cd viewer
npm ci
npm test
npm run build  # regenerates prism/viewer_dist; do not edit generated assets manually
```

After initializing and scanning your chosen repository, use `prism search "query"`,
`prism context <target>`, `prism impact <target>`, or `prism view` to explore it.
`prism graph export --html graph.html` creates an offline viewer; add `--symbols` for
symbol-level data (see `prism graph export --help` for all export options).

For repeatable performance measurements, run `python -m tests.benchmarks.run` from
the project root. It creates a temporary synthetic repository and isolated consent
registry, reports scan/update/query timings, and removes its temporary data. Use
`--enforce` on a dedicated benchmark runner to enforce the specification's latency targets.
