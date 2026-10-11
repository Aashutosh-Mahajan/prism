# T42 local embedding protocol

Compare the current local MiniLM channel with CodeRankEmbed on a fixed source
corpus, the frozen replay requests, and an independent code-to-code set. Record
recall@5/10, cold model load, warm query latency, corpus embedding time, vector
bytes, process peak memory and Windows setup failures. Use the same bounded
symbol text for the primary comparison; report any richer full-code variant
separately. New-file-only replay targets remain in the denominator.

Pinned public revisions, resolved before inference:

- MiniLM: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- CodeRankEmbed: `3c4b60807d71f79b43f3c4363786d9493691f8b1`.
- Jina code 0.5b: `4db235132dafbe56a8b9c5f59b59795ecf58a4a7`.

[CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed) declares MIT.
Its model-specific source is reviewed and pinned before any local execution;
production remote-code trust remains disabled. All model downloads are explicit
benchmark setup, and inference must use local files only.

[Jina code 0.5b](https://huggingface.co/jinaai/jina-code-embeddings-0.5b) declares
CC-BY-NC-4.0. Drop it from the adoption candidates: PRISM's general-purpose
distribution cannot assume noncommercial deployment or a commercial license.
Do not download or run its weights for this experiment. Its metadata and
license remain recorded so the exclusion is explicit rather than a fabricated
performance result.

Keep semantics optional and local. No default model changes without the owner.
API spend is zero; the experiment uses downloaded weights and the installed
local runtime, with no embedding API credentials.

Implementation clarification before the controlled run: installed Transformers 5.7.0
provides native NomicBert support. CodeRank loads its pinned safetensors and
configuration through native AutoModel, with `trust_remote_code=False` and
`local_files_only=True`. No downloaded modelling Python executes.
