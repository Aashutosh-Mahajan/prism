# T01: cost-weighted re-analysis

Original 60 Codex subscription sessions; scoring and pass counts are unchanged.
Unknown gpt-6-luna pricing uses an explicitly flagged comparison proxy.
These figures do not estimate a Codex subscription invoice.

| Arm | Passed | New context | Cache reads | Output | Turns | USD estimate | Fixed-cache USD | pass@1 | pass^k |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline (price proxy) | 10/12 | 278950 | 1530880 | 14758 | 56 | 1.011656 | 1.011656 | 0.833 | 0.750 |
| cli (price proxy) | 10/12 | 296437 | 2016512 | 19919 | 77 | 1.195366 | 1.195366 | 0.833 | 0.500 |
| hook (price proxy) | 12/12 | 235685 | 971264 | 9574 | 42 | 0.761363 | 0.761363 | 1.000 | 1.000 |
| mcp (price proxy) | 12/12 | 221996 | 1381888 | 10480 | 52 | 0.825170 | 0.825170 | 1.000 | 1.000 |
| mcphook (price proxy) | 11/12 | 201819 | 895488 | 9261 | 37 | 0.675346 | 0.675346 | 0.917 | 0.750 |

USD estimates are frozen price-table comparisons, not subscription charges.

Price source: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), retrieved 11 October 2026.

Fixed-cache cost normalizes one-hour writes to the five-minute rate; it does not erase observed differences in cache-hit usage. Missing turn data remains null.
