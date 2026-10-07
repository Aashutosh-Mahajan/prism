# Third-party notices

PRISM's original code is Copyright (c) 2026 AlgoSmiths, licensed under MIT;
see `LICENSE`. The distribution also contains the following Apache-2.0 code.

## Graphify retrieval algorithms

`prism/_vendor/graphify_retrieval.py` adapts `_pick_seeds` and `_bfs` from
[`graphify/serve.py`](https://github.com/Graphify-Labs/graphify/blob/f765dcb3415d60fcfce390868da49e77894f2dc2/graphify/serve.py).

- Upstream: https://github.com/Graphify-Labs/graphify
- Revision: `f765dcb3415d60fcfce390868da49e77894f2dc2` (0.9.79)
- Copyright 2026 Safi Shamsi and the Graphify contributors.
- License: Apache License, Version 2.0.
- Changes: removed NetworkX dependencies; introduced typed callback/mapping
  interfaces, deterministic iteration, bounded per-term seed slots, explicit
  traversal work caps, caller-provided neighbor ordering, and a fixed hub guard.

The upstream license, NOTICE, and retained historical MIT license are included
unchanged in `prism/_vendor/licenses/graphify/` and shipped with the package.
The upstream NOTICE applies to those adapted portions. PRISM's original graph
export adapter in `prism/navigator/graphify.py` remains under PRISM's MIT license.
