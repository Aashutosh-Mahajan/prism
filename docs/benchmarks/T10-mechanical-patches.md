# T10: mechanical-site limit and compact packets

The mechanical-specific literal cap is 400; ordinary retrieval keeps its original
40-line limit. A scan reads one extra occurrence to distinguish 400 exhaustive
sites from a larger list. Common/short identifiers are refused as generic_name;
oversized identifier lists return too_many_sites. Patches remain checked and
write only to PRISM's patch cache, never to indexed source.

Fixture: 80 sites in 12 files gives a patch accepted by git apply --check and
a rendered packet below 400 estimated tokens. At 450 sites the packet explains
the refusal. Compact successful packets group line numbers by file and avoid
repeating all affected source.

Pinned 40-parent replay, before → after:

| Metric | Before | After |
| --- | ---: | ---: |
| File recall | 16.39% | 16.39% |
| Token precision | 18.86% | 18.86% |
| Mean packet tokens | 1,013.18 | 1,013.18 |
| Fixed audit mean packet tokens | 1,317.10 | 1,151.30 |

The replay queries contain no successful mechanical rename, so unchanged replay
scores are expected; the dedicated rename fixture and audit provide coverage.
The Phase 1 precision target is not met by T10 alone.
