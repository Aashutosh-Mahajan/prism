# Offline retrieval scores

Run `python -m tests.benchmarks.context_score <frozen-replay.json>` to print
precision, recall and F1 and save a report keyed by engine commit. The engine
digest and dirty flag also identify the measured working-tree version.

File gold includes newly introduced files. Block gold is the scorable parent-side
diff hunk set; a delivered block and a gold block match on any delivered-line
overlap. Line metrics use exact unions, so repeated source is not counted twice.
The older token precision proxy credits whole bodies from changed files and
should not be confused with these narrower line metrics.

T00 file P/R/F1: 11.63% / 16.39% / 13.61%.
Phase 1 file P/R/F1: 14.75% / 14.75% / 14.75%.
T00 block P/R/F1: 5.24% / 7.95% / 6.31%.
Phase 1 block P/R/F1: 3.61% / 4.30% / 3.93%.
T00 line P/R/F1: 1.98% / 7.49% / 3.14%.
Phase 1 line P/R/F1: 2.26% / 5.70% / 3.24%.

These are commit-subject proxies, not verified task success. The reduced hunk
coverage is disclosed; explicit missing-range recovery remains necessary.
No model runs occur in scoring, so provider cost is unavailable. Transcript-use
share is reported only when explicit observed line ranges are supplied; missing
evidence is not zero use or proof that the agent used every supplied line.

Set `PRISM_CONTEXT_SCORE` and `PRISM_CONTEXT_BASELINE` to frozen score paths and
run `pytest -m context_regression`. The gate uses the owner's approved two-point
file-recall tolerance; no new block/line threshold is silently introduced.
