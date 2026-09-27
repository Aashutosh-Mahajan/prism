# PRISM audit and implementation backlog

Date: 2026-09-27. Scope: current repository, Python checks, frontend build, viewer source, live fixture viewer, and a small synthetic index benchmark. This is an audit and task plan; application code has not been changed.

**Follow-up:** the paragraph above describes the original audit baseline. Implementation has since begun; see [phase status](phase-status.md) for current changes, verification, and remaining work. The findings below are retained as the original backlog rather than presented as all still unfixed.

## Findings at a glance

The implementation is product-specific and worth refining. Preserve its local/offline model, package/file/symbol drill-down, deterministic artifacts, explicit consent, atomic writes, graph node caps, strict typing, and worker-based ForceAtlas2 layout.

The repository is substantially ahead of its README: navigation, MCP, audits, exports, incremental updates, and a graph viewer already exist. Python responsibilities are mostly separated well; the viewer orchestration and CLI are the main large coordination files.

### Verification performed

| Check | Result |
|---|---|
| `python -m pytest` | **187 passed, 1 failed**, 55.39 seconds on local Python 3.14 |
| Failing test | `tests/integration/test_scan.py:73`, `test_golden_tiny` |
| Failure analysis | Only `dependency_graph.json` differs in the generated tiny fixture. Five module entries now contain `community`; the committed golden omits it. The current schema requires it. |
| `python -m ruff check prism tests` | Passed |
| `python -m ruff format --check prism tests` | Passed; 123 files |
| `python -m mypy` | Passed; 106 source files |
| Viewer TypeScript + production build | Passed, built to a temporary audit directory to avoid replacing the shipped bundle |
| Build size | JS 241.19 kB / 61.47 kB gzip; CSS 8.48 kB / 2.55 kB gzip |
| Live fixture viewer | Loaded 10 package nodes and 13 edges with live connection |
| Desktop geometry, 1440 × 900 | Graph width 1170px, height approximately 826px |
| Mobile geometry, 390 × 844 | **Graph width 0px**; sidebar height 754px exceeds workspace height of approximately 652px |
| Mechanical design detector | One warning on the finding severity border. Treated as a false positive: the border communicates a real finding, not arbitrary decoration. |

The suite emitted 8,637 deprecation warnings, primarily from the locally installed pytest-asyncio plugin. This is environment evidence, not thousands of application defects.

### Small index baseline

One `build_index` run per generated repository, 12 modules per package and 10 functions per module, on this machine:

| Files | Symbols | Time |
|---:|---:|---:|
| 30 | 348 | 0.815s |
| 72 | 855 | 1.772s |
| 142 | 1,700 | 3.880s |

These measurements exclude artifact writing and meaningful Git history. They are a starting point, not a large-repository throughput claim or proof of a backend bottleneck.

### Provisional UI audit

Scores are implementation-review judgments, not an accessibility certification or measured frame-rate result.

| Dimension | Score / 4 | Evidence |
|---|---:|---|
| Accessibility | 1 | Hidden checkbox controls, click-only related-node lists, incomplete search semantics |
| Performance | 2 | Worker layout and caps exist; repeated edge scans and unconditional synchronous community detection remain |
| Responsive behavior | 0 | Core graph has zero width at the tested narrow viewport |
| Theming | 2 | CSS tokens and both themes exist; graph palettes and overlay colors are separately hard-coded |
| Implementation integrity | 3 | Coherent graph product; legend and export behavior have correctness gaps |
| Total | **8 / 20** | Major targeted repairs needed; a wholesale rewrite is not justified |

## Task-by-task plan

Priority: P0 blocks a core workflow in the stated context; P1 should be addressed before release; P2 improves scale, maintainability, or usability. Tasks 1–9 are correctness and regression protection. Profile before expanding tasks 10–13.

### 1. Repair the golden/schema mismatch — P1

- Evidence: `tests/integration/test_scan.py:73`, `tests/golden/tiny/dependency_graph.json`, `prism/schemas/dependency_graph.schema.json`.
- Work: review the intended `community` output, verify deterministic assignments and compatibility expectations, then update only the justified golden artifact. Add schema validation of committed golden artifacts if not covered by the existing tests.
- Why: the baseline suite is red, hiding future regressions. Blind regeneration would erase useful evidence.
- Done when: the full suite passes, the artifact satisfies the schema, and repeated generation remains byte-stable.

### 2. Fix the graph's responsive grid placement — P0 on narrow screens

- Evidence: `viewer/src/style.css:111` onward and the max-width 900px media query. At narrow widths the sidebar and panel become absolutely positioned, but the workspace retains `auto 1fr auto`; the stage lands in an auto column and was measured at 0px wide.
- Work: explicitly place the stage or switch the narrow workspace to one column. Anchor drawers to the actual workspace, replace the fixed 90px header assumption, and make the sidebar collapsed or dismissible on narrow screens.
- Why: users can load graph data successfully and still see no graph. Drawers also extend below the available workspace.
- Done when: graph width is positive and usable at 390, 768, 900, 901, and 1440px, including with either panel open and with enlarged text.

### 3. Add frontend regression tests and CI — P1

- Evidence: `viewer/package.json` has build/typecheck scripts but no frontend test command; `.github/workflows/ci.yml` checks only Python.
- Work: add focused tests for encoding, filters, asynchronous state, and graph transformations; add browser tests for boot, search, drill-down, layer switching, responsive geometry, saved views, and static export. Run frontend typecheck/build and essential browser tests in CI.
- Why: Python viewer tests cannot catch a zero-width browser canvas or stale search results.
- Done when: CI detects tasks 2, 4–8 as regressions and verifies that packaged viewer assets match their source build.

### 4. Prevent stale asynchronous UI updates — P1

- Evidence: `viewer/src/main.ts:661` search has debounce but no response sequence guard; selection success is guarded at line 476 but its error path is not. Impact, diff, and path requests can also finish after the view changes.
- Work: introduce cancellation or request generation identifiers, capture query/view identity, and guard both success and failure paths. Clear obsolete search state immediately. Validate URL state instead of relying on TypeScript casts.
- Why: an older query or error can replace the result of the user's latest action.
- Done when: delayed and reordered responses cannot change the current selection, search results, overlays, or closed panel.

### 5. Make graph controls keyboard and screen-reader usable — P1

- Evidence: `.chips input { display: none; }` in `viewer/src/style.css`; click-only `li` entries in `viewer/src/main.ts:493`; incomplete search combobox/listbox semantics; graph exposes a canvas image rather than navigable nodes.
- Work: retain focusable native checkboxes with accessible styling, use buttons/links for related nodes, implement search labeling and active option semantics, provide appropriate tab navigation and focus restoration, and add an accessible node list for equivalent graph exploration.
- Why: graph tasks must not depend on precise pointer input. These are concrete keyboard and semantics gaps related to WCAG 2.1.1 and 4.1.2.
- Done when: search → select → inspect relations → focus local graph works with keyboard only, with meaningful accessible names and announced state.

### 6. Highlight actual path edges — P1

- Evidence: `viewer/src/main.ts:882` stores a path as a node Set; the edge reducer highlights any edge whose two endpoints are in that Set.
- Work: retain ordered path nodes and derive the exact consecutive edge pairs, including directionless fallback behavior. Clear previous path highlighting when no new path exists.
- Why: chords and reverse edges between path nodes can currently appear to be part of the returned path, misrepresenting dependencies.
- Done when: a path through a graph with extra cross-links highlights only the returned hops.

### 7. Align static exports with the live viewer — P1

- Evidence: `viewer/src/data.ts:165` onward. Static package path filtering checks `n.file`, while live filtering matches member files. Static graph lookup can silently fall back to imports for an unavailable layer; an unresolved root can leave the whole graph visible.
- Work: define supported operations explicitly, share or contract-test graph semantics, handle package membership in filters, and show unsupported/unresolved states clearly. Namespace static layout and saved-view storage by project/export identity.
- Why: the same controls should not tell different stories depending on whether the user opened a live server or an HTML export. Generic localStorage keys can mix exports sharing an origin.
- Done when: paired live/static fixtures agree on supported filters, root selection, and paths; unsupported features are visibly unavailable.

### 8. Correct legends and visual meaning — P1

- Evidence: `viewer/src/encode.ts` colors zero findings with `NEUTRAL`, but its findings legend displays the green heat-ramp color for “no findings.” `renderLegend` always describes a dependency/import-cycle relationship regardless of the chosen layer.
- Work: make legends use the same encoding functions as nodes, add a size legend, explain relation direction per layer, expose active overlay meaning, and distinguish unknown values from zero. Handle categories beyond the current top ten explicitly.
- Why: attractive graphs are not useful when users cannot correctly interpret their colors, size, and edges.
- Done when: each color/size/layer/overlay combination has an accurate legend, verified against known node values.

### 9. Harden viewer input and persistence boundaries — P1

- Evidence: `prism/viewer/server.py:255` parses Content-Length outside the error handler and only checks its upper bound. `prism/viewer/api.py:192` accepts numeric layout coordinates without checking finiteness. Saved-view validation checks only object type and size; the client later consumes it through `any`.
- Work: reject malformed and negative lengths, validate bounded numeric query values, finite coordinates, saved-view enums, and camera state. Return consistent client errors and recover from corrupt cached layouts.
- Why: malformed requests or saved data should produce actionable errors rather than request failures or broken graph state.
- Done when: boundary tests cover invalid lengths, NaN/infinity, malformed cache files, invalid enums, and oversized values while preserving loopback/token protections.

### 10. Remove repeated graph-loading work — P2, strong code-level optimization candidate

- Evidence: `viewer/src/main.ts:236` scans all payload edges for each newly placed node; `load` runs Louvain synchronously for every non-empty graph, even when community coloring is unused and index communities exist.
- Work: build adjacency once per payload, use it for placement, reuse indexed communities, and compute missing communities lazily or in a worker. Batch graph attribute changes where supported and measure before/after.
- Why: placement approaches O(new nodes × edges), and synchronous clustering competes with input and painting. Worker-based ForceAtlas2 itself is already a good choice.
- Done when: representative sparse and dense graph benchmarks show reduced load/main-thread work without changing graph meaning.

### 11. Reduce live-update and animation work — P2

- Evidence: `viewer/src/main.ts:180` refreshes the renderer each animation frame while a 20-second activity trail remains. `onIndex` reloads the entire graph for each event. No reduced-motion handling was found.
- Work: animate only the short pulse interval, schedule static trail expiry without continuous frames, respect reduced motion, pause unnecessary work in hidden tabs, and coalesce rapid index events. Consider graph deltas only after measuring full reload cost.
- Why: sustained agent activity can keep a large graph repainting and repeatedly rebuilding after the useful animation has ended.
- Done when: idle activity trails do not cause continuous redraws, burst events coalesce, and reduced-motion users retain clear static state feedback.

### 12. Establish reproducible performance budgets — P2, precedes broad backend optimization

- Evidence: `tests/benchmarks/synth.py` provides a useful generator. The audit baseline is small and single-run.
- Work: add repeatable cold scan, no-change update, one-file edit, deletion, search, graph payload, memory, first-interaction, and frame-time benchmarks. Include dense graphs, large repositories, and real Git history; record environment and median/tail results.
- Why: “highly optimized” needs measurable targets. Bundle size alone does not identify the dominant cost.
- Done when: agreed budgets and a repeatable baseline exist, with regression checks stable enough for CI or a scheduled benchmark job.

### 13. Optimize backend graph/query work from profiles — P2

- Evidence: `prism/viewer/model.py:434` builds file nodes even for symbol requests; `graph` reconstructs raw relations and recomputes import cycles per request. `build_index` rebuilds derived graph/extractor stages after cached parsing.
- Work: profile these stages, cache immutable graph representations/adjacency/cycles by artifact fingerprint where beneficial, avoid unnecessary node construction, and optimize incremental derived stages only where measured. Retain deterministic ordering and caps.
- Why: parsing reuse does not automatically eliminate downstream work; repeated viewer requests may benefit from reuse.
- Done when: representative scan/update/API timings improve with byte-equivalence, invalidation, and memory-bound tests. Do not add parallelism or caches without evidence.

### 14. Exercise concurrency and snapshot consistency — P2 investigation

- Evidence: the viewer uses ThreadingHTTPServer. `ViewerBackend.store()` locks store replacement but returns the shared store for use outside the lock; a refresh can close the old connection while another request still holds it. Layout saves perform read/merge/write without a transaction across requests.
- Work: add concurrent search/detail/index-refresh and layout-save tests. Use stable request-scoped snapshots or explicit connection lifetime management and serialize merging writes as justified.
- Why: atomic file replacement prevents torn files, but does not alone prevent lost updates or use of a closed shared connection.
- Done when: stress tests show consistent request results and preserved writes. This risk was identified from code; an actual concurrent failure was not reproduced during this audit.

### 15. Split large orchestration files by responsibility — P2

- Evidence: `viewer/src/main.ts` is approximately 1,020 lines, combining state, rendering, data loading, interactions, panels, filters, persistence, and live events. `prism/cli.py` is approximately 945 lines.
- Work: after regression coverage, extract typed viewer state/controller, graph renderer/layout, selection panel, search, controls, and live synchronization. Split CLI command groups while retaining shared error handling and stable commands.
- Why: isolating responsibilities makes fixes and performance experiments easier to review. The existing Python package structure should be preserved rather than rewritten.
- Done when: modules have explicit contracts, no circular dependencies, and unchanged public behavior; avoid a framework migration without a separate need.

### 16. Improve graph readability and interaction hierarchy — P2

- Evidence: existing size thresholds, package aggregation, local focus, and collapsible controls provide a useful foundation. All edges use arrows, group colors are hash-selected from 12 colors, and the legend disappears below 900px.
- Work: make important/selected labels reliable, tune density by zoom, provide collision-resistant categorical assignments, use layer-appropriate edge direction and styles, and prioritize local-neighborhood exploration. Keep an accessible compact legend on narrow screens, improve touch targets, and coordinate selected/hovered/path/diff states.
- Why: the graph should answer “what depends on this?” and “what changed?” quickly, without relying on a dense web of indistinguishable marks.
- Done when: representative dense/sparse graphs and both themes support those tasks without ambiguous encodings or overlapping controls. Preserve the current visual identity unless a redesign is separately requested.

### 17. Consolidate themes and document UI conventions — P2

- Evidence: CSS theme tokens exist, while `encode.ts` and `main.ts` carry separate categorical, heat, ring, and diff colors. PRODUCT.md and DESIGN.md are absent.
- Work: define a shared semantic graph palette, spacing/type/control conventions, state precedence, accessibility expectations, and brief product/task context. Check contrast in both themes instead of replacing colors speculatively.
- Why: consistent rules prevent later graph features from conflicting with existing color meaning and interaction behavior.
- Done when: graph/UI colors resolve through documented tokens and dark/light visual checks pass.

### 18. Make packaging, dependencies, and docs match the product — P1 for release readiness

- Evidence: README says Phase 1 and describes navigation/MCP as future work. CI covers Python 3.10–3.13 while package classifiers also claim 3.14. Optional tree-sitter dependencies are not installed in the CI job. Built viewer assets are shipped with Python package data.
- Work: update feature status, CLI/viewer/export instructions, architecture, and troubleshooting. Test optional parsers in at least one job, test the claimed Python versions, build/install a wheel in a clean environment, and smoke-test packaged viewer assets without Node. Isolate development dependencies so unrelated pytest plugins do not dominate warnings.
- Why: a source checkout passing tests does not prove the installed package includes the working viewer, optional language support, or correct instructions.
- Done when: a clean install can run documented workflows offline, release assets are reproducible, and the support matrix matches the metadata.

## Suggested execution sequence

1. Repair the baseline and visible blocking behavior: tasks 1–2.
2. Add focused frontend regression coverage while fixing tasks 4–9; wire it into CI through task 3.
3. Establish budgets with task 12; implement and measure tasks 10–11, then use profiles to scope task 13.
4. Investigate snapshot concurrency with task 14 and refactor under test with task 15.
5. Complete graph readability/theme work with tasks 16–17, followed by a bounded visual and accessibility polish pass.
6. Finish release/documentation work with task 18 and rerun the relevant full checks.

For UI work, the applicable Impeccable passes are `adapt` (task 2), `harden` (tasks 4–9), `optimize` (tasks 10–11), `clarify` (task 8), `document` (task 17), and finally `polish`. The implementation tasks and their acceptance checks above are the primary plan.

## Limits

No application code was changed, no goldens were regenerated, and no index was initialized in the actual project. Live viewing used a temporary fixture and an isolated PRISM config directory. Full accessibility certification, large-repository frame-rate tests, semantic-model integration, and all OS/Python combinations were not performed. Findings explicitly marked as candidates or investigations require measurements or reproduction before claiming a defect or speedup.
