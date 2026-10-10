## 18. Success Metrics

- **Token savings:** a benchmark harness replays scripted tasks on fixture repos and counts tokens read by an agent with vs. without PRISM. Target: ≥ 70% fewer tokens spent on orientation.
- **Freshness:** index never more than one hook-cycle behind the working tree when hooks are installed.
- **Accuracy:** `prism locate` top-1 correct ≥ 95% on a labeled query set; call-graph edge precision tracked per language.
- **Audit usefulness:** on the seeded-bug fixture, following `prism-audit` finds ≥ 80% of seeded bugs with `confirmed` evidence.
- **Viewer:** meets the Section 11.5 targets; a new user can find any symbol and see its callers visually within 10 seconds of `prism view`.

