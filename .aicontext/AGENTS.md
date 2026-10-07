# prism-ctx — Agent Brief

## Facts
<!-- prism:generated:facts -->
- Languages: python (166), typescript (19), javascript (3)
- Key dependencies: viewer, tomli, jsonschema, sigma, @sigma, graphology, graphology-communities-louvain, graphology-layout-forceatlas2
- Entry points: `prism` (prism/entry.py), `prism.__main__` (prism/__main__.py), `prism.hooks.update_job.main` (prism/hooks/update_job.py), `prism.cli.main` (prism/cli.py)
- Commands: lint: `ruff check .`, test: `python -m pytest -q`, test (viewer): `cd viewer && npm run test`, typecheck: `python -m mypy .`, typecheck (viewer): `cd viewer && npm run typecheck`
- Top modules by importance: `prism.core.models`, `prism.core.errors`, `prism.core.paths`, `prism.writers.json_writer`, `viewer.src.types`, `prism.navigator.store`, `prism.navigator.text`, `prism.config`
- Size: 188 files, 1531 symbols, 48 test files
<!-- /prism:generated:facts -->

## Purpose
<!-- prism:narrative:purpose -->
Offline project knowledge for coding agents, with bounded evidence through CLI, MCP and hooks.
<!-- /prism:narrative:purpose -->

## Architecture
<!-- prism:narrative:architecture -->
lifecycle/pipeline parse source; writers persist .aicontext facts. navigator.api shares CLI/MCP retrieval. Hooks refresh edits and inject context. SQLite caches hold postings and session ranges.
<!-- /prism:narrative:architecture -->

## Conventions
<!-- prism:narrative:conventions -->
Core uses no LLM/network or source edits. Verify revisions and budgets; persist via writers. Run pytest, ruff and mypy.
<!-- /prism:narrative:conventions -->

## Navigation
<!-- prism:generated:navigation -->
Start with `prism task "<request>"`: it returns the matching code, every exact occurrence of the strings and names in the request, call sites and tests in one call. Use `prism context <symbol>` or `prism impact <symbol>` for follow-ups. If `prism status` says the index is stale, run `prism update`.
<!-- /prism:generated:navigation -->
