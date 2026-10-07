# prism-ctx — Agent Brief

## Facts
<!-- prism:generated:facts -->
- Languages: python (162), typescript (19), javascript (3)
- Key dependencies: viewer, tomli, jsonschema, sigma, @sigma, click, graphology, graphology-communities-louvain
- Entry points: `prism` (prism/entry.py), `prism.__main__` (prism/__main__.py), `prism.hooks.update_job.main` (prism/hooks/update_job.py), `prism.cli.main` (prism/cli.py)
- Commands: lint: `ruff check .`, test: `python -m pytest -q`, test (viewer): `cd viewer && npm run test`, typecheck: `python -m mypy .`, typecheck (viewer): `cd viewer && npm run typecheck`
- Top modules by importance: `prism.core.models`, `prism.core.errors`, `prism.core.paths`, `prism.writers.json_writer`, `viewer.src.types`, `prism.navigator.store`, `prism.config`, `prism.writers.manifest`
- Size: 184 files, 1494 symbols, 46 test files
<!-- /prism:generated:facts -->

## Purpose
<!-- prism:narrative:purpose -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:purpose -->

## Architecture
<!-- prism:narrative:architecture -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:architecture -->

## Conventions
<!-- prism:narrative:conventions -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:conventions -->

## Navigation
<!-- prism:generated:navigation -->
Start with `prism task "<request>"`: it returns the matching code, every exact occurrence of the strings and names in the request, call sites and tests in one call. Use `prism context <symbol>` or `prism impact <symbol>` for follow-ups. If `prism status` says the index is stale, run `prism update`.
<!-- /prism:generated:navigation -->
