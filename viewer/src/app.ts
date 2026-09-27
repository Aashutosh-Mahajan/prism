// The viewer's state and core operations. UI modules render from here; they never own state.
import Graph from "graphology";
import louvain from "graphology-communities-louvain";
import type Sigma from "sigma";

import { ApiError, type DataSource } from "./data";
import { buildContext, nodeColor, nodeSize, nodeType, type ColorBy, type EncodeContext, type SizeBy } from "./encode";
import {
  adjacency, nearestInDirection, pathEdges, percentile, relations, RequestGeneration, seedPositions,
  type Direction, type Relations,
} from "./graph-utils";
import { renderInspector } from "./inspector";
import { LayoutController } from "./layout";
import { createRenderer } from "./renderer";
import { palette } from "./theme";
import type { Details, Filters, GNode, GraphPayload, Layer, Level } from "./types";
import { $, announce, plural, toast } from "./ui";

export const LEVELS: Level[] = ["package", "file", "symbol"];
export const LAYERS: Layer[] = ["import", "call", "tests", "cochange", "routes"];
export const LAYER_LABELS: Record<Layer, string> = {
  import: "Imports", call: "Calls", tests: "Tests", cochange: "Changed together", routes: "Routes",
};
export const LEVEL_LABELS: Record<Level, string> = { package: "Packages", file: "Files", symbol: "Symbols" };
export const KIND_LABELS: Record<string, string> = {
  cluster: "Package", package: "Package", module: "Module", class: "Class", function: "Function",
  method: "Method", test: "Test", route: "Route",
};

export const emptyFilters = (): Filters => ({
  path: "", kinds: [], hide_tests: false, orphans_only: false, min_rank: 0, min_risk: 0, changed_since: "",
});

export interface ViewState {
  level: Level;
  layer: Layer;
  root: string | null;
  depth: number;
  filters: Filters;
  colorBy: ColorBy;
  sizeBy: SizeBy;
  drill: string | null;
  selected: string | null;
  focused: string | null; // keyboard focus on the canvas
  hovered: string | null;
  rings: Map<string, number> | null;
  path: Set<string> | null;
  pathEdges: Set<string>;
  diff: Map<string, string> | null;
  showCycles: boolean;
  showDead: boolean;
  showActivity: boolean;
  showLabels: boolean;
  trail: Map<string, number>;
  pulses: Map<string, number>;
}

type Listener = () => void;

function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

/** URL parameters are untrusted input: accept only known values. */
export function stateFromUrl(search: string): Partial<ViewState> {
  const params = new URLSearchParams(search);
  const focus = params.get("focus");
  const depth = Number(params.get("depth"));
  return {
    level: oneOf(params.get("level"), LEVELS, focus ? "file" : "package"),
    layer: oneOf(params.get("layer"), LAYERS, "import"),
    root: focus && focus.length < 500 ? focus : null,
    depth: Number.isInteger(depth) && depth >= 1 && depth <= 4 ? depth : 2,
  };
}

export class App {
  readonly graph = new Graph({ type: "directed", multi: false, allowSelfLoops: false });
  readonly renderer: Sigma;
  readonly layout: LayoutController;
  readonly state: ViewState;
  payload: GraphPayload | null = null;
  rel: Relations = { incoming: new Map(), outgoing: new Map() };
  neighbors = new Map<string, Set<string>>();
  community = new Map<string, number>();
  encoding: EncodeContext | null = null;
  savedPositions: Record<string, [number, number]> = {};
  readonly reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  private readonly detailCache = new Map<string, Promise<Details>>();
  private readonly loads = new RequestGeneration();
  private readonly overlays = new RequestGeneration();
  private rankPercentiles = new Map<string, number>();
  private readonly listeners = { graph: new Set<Listener>(), selection: new Set<Listener>(), view: new Set<Listener>() };

  constructor(readonly source: DataSource, container: HTMLElement, initial: Partial<ViewState>) {
    this.state = {
      level: "package", layer: "import", root: null, depth: 2, filters: emptyFilters(),
      colorBy: "group", sizeBy: "rank", drill: null, selected: null, focused: null, hovered: null,
      rings: null, path: null, pathEdges: new Set(), diff: null,
      showCycles: true, showDead: false, showActivity: true, showLabels: true,
      trail: new Map(), pulses: new Map(),
      ...initial,
    };
    this.renderer = createRenderer(this, container);
    this.layout = new LayoutController(this);
  }

  on(event: keyof App["listeners"], fn: Listener): void {
    this.listeners[event].add(fn);
  }

  emit(event: keyof App["listeners"]): void {
    for (const fn of this.listeners[event]) fn();
  }

  refresh(): void {
    this.renderer.refresh({ skipIndexation: true });
  }

  node(id: string): GNode | null {
    return this.graph.hasNode(id) ? (this.graph.getNodeAttribute(id, "data") as GNode) : null;
  }

  importancePercentile(id: string): number {
    return this.rankPercentiles.get(id) ?? 0;
  }

  // --- loading ----------------------------------------------------------------------------

  setBusy(message: string | null): void {
    const loading = $("loading");
    loading.hidden = message === null;
    if (message) $("loading-text").textContent = message;
    $("spectrum").classList.toggle("busy", message !== null || this.layout.running);
  }

  async load(opts: { keepCamera?: boolean; pulse?: Iterable<string> } = {}): Promise<boolean> {
    const request = this.loads.next();
    const s = this.state;
    // Imports and co-change are file-level relations; at symbol level the call graph is the useful view.
    if (s.level === "symbol" && (s.layer === "import" || s.layer === "cochange")) s.layer = "call";
    this.setBusy(`Loading ${LEVEL_LABELS[s.level].toLowerCase()}`);
    let payload: GraphPayload;
    try {
      payload = await this.source.graph({ level: s.level, layer: s.layer, root: s.root, depth: s.depth, filters: s.filters });
    } catch (err) {
      if (!this.loads.current(request)) return false;
      this.setBusy(null);
      if (err instanceof ApiError && s.root) {
        toast(`${err.message}. Showing the whole graph instead.`, true);
        s.root = null;
        return this.load(opts);
      }
      toast(err instanceof Error ? err.message : String(err), true);
      return false;
    }
    if (!this.loads.current(request)) return false;
    this.applyPayload(payload, opts);
    this.setBusy(null);
    return true;
  }

  private applyPayload(payload: GraphPayload, opts: { keepCamera?: boolean; pulse?: Iterable<string> }): void {
    const g = this.graph;
    this.payload = payload;
    this.state.hovered = null;
    this.neighbors = adjacency(payload.edges);
    this.rel = relations(payload.edges);
    const previous = new Map<string, { x: number; y: number }>();
    g.forEachNode((id, a) => previous.set(id, { x: a.x as number, y: a.y as number }));
    const pinned = new Set(g.filterNodes((_, a) => Boolean(a.fixed)));
    this.layout.stop();

    // Place nodes: saved position > position in the previous view > near placed neighbours > seeded cluster.
    const unplaced = payload.nodes.filter((n) => !this.savedPositions[n.id] && !previous.has(n.id));
    const mostlyNew = unplaced.length > payload.nodes.length * 0.3;
    const seeds = mostlyNew ? seedPositions(unplaced, payload.nodes.length > 1500 ? 1.4 : 1) : null;
    const place = (n: GNode): { x: number; y: number } => {
      const saved = this.savedPositions[n.id];
      if (saved) return { x: saved[0], y: saved[1] };
      const prev = previous.get(n.id);
      if (prev) return prev;
      if (seeds) return seeds.get(n.id)!;
      const pts: { x: number; y: number }[] = [];
      for (const other of this.neighbors.get(n.id) ?? []) {
        const p = previous.get(other) ?? (this.savedPositions[other] && { x: this.savedPositions[other][0], y: this.savedPositions[other][1] });
        if (p) pts.push(p);
      }
      if (pts.length) {
        const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length;
        const cy = pts.reduce((a, p) => a + p.y, 0) / pts.length;
        return { x: cx + (Math.random() - 0.5) * 8, y: cy + (Math.random() - 0.5) * 8 };
      }
      return seedPositions([n]).get(n.id)!;
    };

    g.clear();
    for (const n of payload.nodes) {
      g.addNode(n.id, { ...place(n), label: n.label, data: n, fixed: pinned.has(n.id) || undefined });
    }
    for (const e of payload.edges) {
      if (g.hasNode(e.source) && g.hasNode(e.target) && !g.hasEdge(e.source, e.target)) {
        g.addEdgeWithKey(e.id, e.source, e.target, {
          weight: e.weight, confidence: e.confidence, cycle: Boolean(e.cycle),
          size: Math.min(2.4, 0.5 + Math.log1p(e.weight) * 0.35),
        });
      }
    }
    const ranks = payload.nodes.map((n) => n.rank);
    this.rankPercentiles = new Map(payload.nodes.map((n) => [n.id, percentile(ranks, n.rank)]));
    this.community = new Map();
    if (this.state.colorBy === "community") this.ensureCommunities();
    this.encode();
    this.tuneRenderer();

    const s = this.state;
    if (s.selected && !g.hasNode(s.selected)) this.closeInspector();
    if (s.focused && !g.hasNode(s.focused)) s.focused = null;
    for (const id of opts.pulse ?? []) if (g.hasNode(id)) s.pulses.set(id, performance.now());

    this.emit("graph");
    this.emit("view");
    if (unplaced.length > 0) this.layout.run(unplaced.length === payload.nodes.length);
    if (!opts.keepCamera) this.fit();
    if (s.root && g.hasNode(s.root) && s.selected !== s.root) this.select(s.root, { moveCamera: false });
  }

  /** Denser graphs hide edges while panning and show fewer labels, so interaction stays smooth. */
  private tuneRenderer(): void {
    const n = this.graph.order;
    const e = this.graph.size;
    this.renderer.setSetting("hideEdgesOnMove", e > 1500);
    this.renderer.setSetting("labelRenderedSizeThreshold", n > 3000 ? 11 : n > 800 ? 9 : 6);
    this.renderer.setSetting("labelDensity", n > 3000 ? 0.35 : 0.7);
  }

  ensureCommunities(): void {
    if (this.community.size || !this.graph.size || !this.payload?.nodes.some((n) => n.community === undefined)) return;
    try {
      this.community = new Map(Object.entries(louvain(this.graph, { getEdgeWeight: "weight" }) as Record<string, number>));
    } catch {
      /* optional: nodes without an index community stay neutral */
    }
  }

  encode(): void {
    const nodes: GNode[] = this.graph.mapNodes((_, a) => a.data as GNode);
    const ctx = buildContext(nodes, this.community);
    this.encoding = ctx;
    this.graph.forEachNode((id, a) => {
      const n = a.data as GNode;
      const color = nodeColor(n, this.state.colorBy, ctx);
      const hollow = n.kind === "cluster" || n.kind === "test" || n.kind === "route";
      this.graph.mergeNodeAttributes(id, {
        color,
        innerColor: hollow ? palette.canvas : color,
        size: nodeSize(n, this.state.sizeBy, ctx),
        type: nodeType(n),
        dead: Boolean(n.dead),
      });
    });
    this.emit("view");
  }

  // --- camera -----------------------------------------------------------------------------

  private duration(ms: number): number {
    return this.reducedMotion.matches ? 0 : ms;
  }

  fit(): void {
    void this.renderer.getCamera().animatedReset({ duration: this.duration(300) });
  }

  zoom(direction: 1 | -1): void {
    const camera = this.renderer.getCamera();
    if (direction > 0) void camera.animatedZoom({ duration: this.duration(200) });
    else void camera.animatedUnzoom({ duration: this.duration(200) });
  }

  centerOn(id: string, zoomIn = true): void {
    const d = this.renderer.getNodeDisplayData(id);
    if (!d) return;
    const camera = this.renderer.getCamera();
    const ratio = zoomIn ? Math.min(camera.ratio, 0.4) : camera.ratio;
    void camera.animate({ x: d.x, y: d.y, ratio }, { duration: this.duration(400) });
  }

  isOnScreen(id: string): boolean {
    const d = this.renderer.getNodeDisplayData(id);
    if (!d) return false;
    const p = this.renderer.framedGraphToViewport({ x: d.x, y: d.y });
    const { width, height } = this.renderer.getDimensions();
    return p.x > 40 && p.y > 40 && p.x < width - 40 && p.y < height - 40;
  }

  // --- selection, focus, details -------------------------------------------------------------

  details(id: string): Promise<Details> {
    let pending = this.detailCache.get(id);
    if (!pending) {
      pending = this.source.node(id);
      this.detailCache.set(id, pending);
      pending.catch(() => this.detailCache.delete(id));
    }
    return pending;
  }

  prefetch(id: string): void {
    if (!this.detailCache.has(id)) void this.details(id).catch(() => undefined);
  }

  invalidateDetails(): void {
    this.detailCache.clear();
  }

  select(id: string, opts: { moveCamera?: boolean; focusPanel?: boolean } = {}): void {
    const s = this.state;
    s.selected = id;
    s.focused = id;
    this.refresh();
    if (opts.moveCamera ?? true) this.centerOn(id);
    this.emit("selection");
    renderInspector(this, id, opts.focusPanel ?? false);
  }

  private returnFocus: HTMLElement | null = null;

  rememberFocus(): void {
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body && !$("panel").contains(active)) this.returnFocus = active;
  }

  closeInspector(): void {
    this.state.selected = null;
    $("panel").hidden = true;
    this.refresh();
    this.emit("selection");
    if (this.returnFocus && document.contains(this.returnFocus)) this.returnFocus.focus();
    this.returnFocus = null;
  }

  describe(id: string): string {
    const n = this.node(id);
    if (!n) return id;
    const inc = this.rel.incoming.get(id)?.length ?? 0;
    const out = this.rel.outgoing.get(id)?.length ?? 0;
    const where = n.kind === "cluster" ? plural(n.files ?? 0, "file") : n.file ?? "";
    return `${n.label}, ${KIND_LABELS[n.kind] ?? n.kind}${where ? `, ${where}` : ""}. ${plural(inc, "incoming link")}, ${plural(out, "outgoing link")}.`;
  }

  setFocus(id: string | null, announceIt = true): void {
    this.state.focused = id;
    this.refresh();
    if (!id) return;
    if (!this.isOnScreen(id)) this.centerOn(id, false);
    if (announceIt) announce(`${this.describe(id)} Press Enter to inspect.`);
    this.emit("selection");
  }

  /** Arrow-key navigation over the canvas, in screen space. */
  moveFocus(direction: Direction): void {
    const g = this.graph;
    if (!g.order) return;
    const viewport = (id: string) => {
      const d = this.renderer.getNodeDisplayData(id)!;
      return this.renderer.framedGraphToViewport({ x: d.x, y: d.y });
    };
    const current = this.state.focused ?? this.state.selected;
    if (!current || !g.hasNode(current)) {
      const { width, height } = this.renderer.getDimensions();
      let best: string | null = null;
      let bestD = Infinity;
      g.forEachNode((id) => {
        const p = viewport(id);
        const d = (p.x - width / 2) ** 2 + (p.y - height / 2) ** 2;
        if (d < bestD) (bestD = d), (best = id);
      });
      this.setFocus(best);
      return;
    }
    const from = viewport(current);
    // Prefer direct neighbours so arrows follow the structure; fall back to any node.
    const pick = (ids: Iterable<string>): string | null => {
      const candidates: [string, { x: number; y: number }][] = [];
      for (const id of ids) if (id !== current) candidates.push([id, viewport(id)]);
      return nearestInDirection(from, candidates, direction);
    };
    const around = this.neighbors.get(current);
    const next = (around?.size ? pick(around) : null) ?? pick(g.nodes());
    if (next) this.setFocus(next);
    else announce(`No node further ${direction}.`);
  }

  // --- navigation ----------------------------------------------------------------------------

  setLevel(level: Level): void {
    const button = document.querySelector<HTMLButtonElement>(`#level button[data-level="${level}"]`);
    if (button?.disabled) {
      toast(button.title || "This level is not available here.", true);
      return;
    }
    const s = this.state;
    s.level = level;
    s.rings = null;
    s.path = null;
    s.diff = null;
    if (level === "package") {
      s.drill = null;
      s.filters.path = "";
    }
    void this.load();
  }

  setRoot(id: string | null): void {
    this.state.root = id;
    void this.load();
  }

  drillInto(n: GNode): void {
    const s = this.state;
    s.drill = n.group;
    s.root = null;
    s.filters.path = n.dir ? (/\.[a-z]+$/.test(n.dir) ? n.dir : `${n.dir}/*`) : "";
    this.setLevel("file");
  }

  openNode(id: string): void {
    const n = this.node(id);
    if (!n) return;
    if (n.kind === "cluster") this.drillInto(n);
    else if (this.state.level === "file") {
      this.state.root = id;
      this.setLevel("symbol");
    }
  }

  /** A reference from the inspector (symbol id, module id, or path) to a node in view, if any. */
  mapToNode(ref: string): string | null {
    if (this.graph.hasNode(ref)) return ref;
    let found: string | null = null;
    let bestLength = -1;
    this.graph.forEachNode((id, a) => {
      const n = a.data as GNode;
      if (n.file === ref) {
        found = id;
        bestLength = Infinity;
      } else if (n.module && (ref === n.module || ref.startsWith(`${n.module}.`)) && n.module.length > bestLength) {
        found = id;
        bestLength = n.module.length;
      }
    });
    return found;
  }

  jumpTo(ref: string): void {
    const id = this.mapToNode(ref);
    if (id && (id === ref || this.state.level !== "symbol")) {
      this.select(id);
      return;
    }
    this.state.root = ref;
    void this.load().then((ok) => ok && this.graph.hasNode(ref) && this.select(ref));
  }

  // --- overlays ------------------------------------------------------------------------------

  clearOverlays(): void {
    const s = this.state;
    this.overlays.next();
    s.rings = null;
    s.path = null;
    s.pathEdges = new Set();
    s.diff = null;
    this.refresh();
    this.emit("view");
  }

  async showBlast(id: string): Promise<void> {
    const request = this.overlays.next();
    try {
      const r = await this.source.impact(id, this.state.level);
      if (!this.overlays.current(request)) return;
      const s = this.state;
      s.rings = new Map(Object.entries(r.rings));
      s.path = null;
      s.diff = null;
      this.refresh();
      this.emit("view");
      const tests = r.tests.length ? `, ${plural(r.tests.length, "test")} to run` : "";
      toast(`${plural(r.totals.files, "file")} and ${plural(r.totals.symbols, "symbol")} depend on this${tests}.`);
    } catch (err) {
      if (this.overlays.current(request)) toast(err instanceof Error ? err.message : String(err), true);
    }
  }

  async showDiff(since: string): Promise<void> {
    if (!since) return;
    const request = this.overlays.next();
    try {
      const d = await this.source.diff(since);
      if (!this.overlays.current(request)) return;
      const changedIds = new Set(d.changed_ids);
      const map = new Map<string, string>();
      this.graph.forEachNode((id, a) => {
        const n = a.data as GNode;
        if (n.file && d.files[n.file]) map.set(id, d.files[n.file]);
        if (changedIds.has(id)) map.set(id, map.get(id) ?? "M");
        if (n.kind === "cluster" && n.dir && Object.keys(d.files).some((f) => f === n.dir || f.startsWith(`${n.dir}/`))) {
          map.set(id, "M");
        }
      });
      const s = this.state;
      s.diff = map;
      s.rings = null;
      s.path = null;
      this.refresh();
      this.emit("view");
      const deleted = Object.values(d.files).filter((v) => v === "D").length;
      toast(`${plural(map.size, "node")} changed since ${since}${deleted ? ` (${plural(deleted, "deleted file")} not drawn)` : ""}.`);
    } catch (err) {
      if (this.overlays.current(request)) toast(err instanceof Error ? err.message : String(err), true);
    }
  }

  async findPath(from: string, to: string): Promise<string> {
    const request = this.overlays.next();
    const s = this.state;
    const r = await this.source.path(from, to, s.layer === "routes" ? "import" : s.layer, s.level);
    if (!this.overlays.current(request)) return "";
    if (!r.nodes.length) {
      s.path = null;
      s.pathEdges = new Set();
      this.refresh();
      return "No path connects these in the current view.";
    }
    s.path = new Set(r.nodes);
    s.pathEdges = pathEdges(r.nodes, r.directed);
    s.rings = null;
    s.diff = null;
    this.refresh();
    this.emit("view");
    const labels = r.nodes.map((id) => this.node(id)?.label ?? id);
    return `${plural(r.nodes.length - 1, "step")}${r.directed ? "" : " (ignoring direction)"}: ${labels.join(" → ")}`;
  }

  flashSpectrum(): void {
    const bar = $("spectrum");
    bar.classList.add("flash");
    window.setTimeout(() => bar.classList.remove("flash"), 900);
  }
}
