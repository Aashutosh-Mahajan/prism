---
name: Feature request
about: Suggest an improvement to PRISM
title: ""
labels: enhancement
---

**The problem**
What are you or your agent trying to do, and what gets in the way?

**The proposal**
What should PRISM do? Which surface: CLI, MCP tool, skill, viewer, artifact?

**Design checklist** (see CLAUDE.md §20)

- [ ] Works offline, with no API keys
- [ ] Doesn't make the agent read more by default (budgeted, on demand)
- [ ] Keeps the index deterministic; any schema change is versioned with a migration
- [ ] Keeps `update` under 0.5 s per file and queries under 200 ms
- [ ] Needs no configuration before first use
- [ ] Never touches user source code; stays opt-in

**Alternatives considered**
