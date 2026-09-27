## What and why

<!-- The problem this solves and the approach taken. Link the issue: Fixes #123 -->

## How it was tested

<!-- Tests added or changed, manual checks, benchmark numbers if performance-related. -->

## Checklist

- [ ] `ruff check prism tests` and `ruff format --check prism tests` pass
- [ ] `mypy` passes
- [ ] `pytest` passes (sockets are blocked)
- [ ] Viewer changed? `npm test` and `npm run build` in `viewer/`, rebuilt `prism/viewer_dist` committed
- [ ] Artifact output changed? Golden files regenerated and reviewed
- [ ] Schema changed? Version bumped, migration added, skills and JSON Schemas updated
- [ ] Agent-facing text (brief, packs, skills) stays within its token budget
- [ ] Docs and CHANGELOG (*Unreleased*) updated
- [ ] Still offline, no API keys, deterministic, opt-in (CLAUDE.md §4)
