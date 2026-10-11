# T42 local embedding comparison

Keep MiniLM as the optional default. CodeRank improves file recall at five,
ties at ten, and loses one code-to-code hit at five. The larger cold-start and
memory footprint do not justify a default change on these small datasets.

| Measurement | MiniLM-L6 | CodeRankEmbed |
|---|---:|---:|
| File recall@5 (61 targets) | 14/61, 22.95% | 18/61, 29.51% |
| File recall@10 | 19/61, 31.15% | 19/61, 31.15% |
| Code recall@5 (16 targets) | 12/16, 75% | 11/16, 68.75% |
| Code recall@10 | 16/16, 100% | 16/16, 100% |
| Cold model/runtime load | 0.249 s | 64.561 s |
| Embed 1,922 distinct symbol texts | 162.214 s | 28.830 s |
| Vector bytes | 2,952,192 | 5,904,384 |
| Warm query median / p95 | 20.73 / 30.10 ms | 13.90 / 24.87 ms |
| Peak process working set | 927,309,824 bytes | 1,493,172,224 bytes |
| Runtime | production NumPy, CPU | native Transformers, CUDA |

CPU and GPU differ: timings describe these installations, not a controlled
comparison of model speed. Runs used separate processes sequentially, as the
raw timestamps show. Windows runtime already contained Torch 2.11.0+cu126,
Transformers 5.7.0, NumPy 2.5.2 and Sentence Transformers 5.4.1. MiniLM uses
PRISM's existing lightweight implementation. CodeRank needs the substantially
larger optional ML runtime; no dependency was added to the default install.

The file task set comprises the 40 frozen T00 historical parent trees. All 61
gold targets remain in the denominator, including new files absent from their
parent tree. This semantic channel indexes Python symbols; documentation-only
and non-Python targets cannot be retrieved here. The independent code set has
nine real cross-file AST twins with 16 gold targets; a query cannot retrieve
itself. Both models receive the same production 600-character symbol text.
Small datasets and no confidence interval limit the strength of this result.

Pinned revisions and license decisions are in the
registration. CodeRank uses its
model-card query prefix, normalized CLS vectors, pinned safetensors, native
NomicBert support, and disabled remote-code trust. Jina 0.5b is excluded before
weight download because its CC-BY-NC-4.0 license does not support an unrestricted
general-purpose deployment recommendation; no performance result is claimed.
API spend: zero. Model inference is local and offline.

Dataset SHA256:
`afa8d9b9bce135e54d5001014258d424ba4c776137762e3d3d5a94a0da750f57`.
Regenerate it with `python -m tests.benchmarks.embedding_bakeoff prepare
--report output/benchmarks/replay-baseline.json --dataset output/benchmarks/embedding-dataset.json`
(use the committed frozen T00 replay if the local file has been removed).
The script's `--help` documents local weight paths and model runs.
[MiniLM raw scores](minilm.json) and [CodeRank raw scores](coderank.json)
include every ranked file and code-case result. Weights and credentials are
excluded from Git. No production semantic defaults changed.
