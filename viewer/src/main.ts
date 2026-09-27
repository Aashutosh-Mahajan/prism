import "./style.css";

import { createNodeBorderProgram } from "@sigma/node-border";
import { NodeSquareProgram } from "@sigma/node-square";
import Graph from "graphology";
import louvain from "graphology-communities-louvain";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import Sigma from "sigma";
import { EdgeArrowProgram } from "sigma/rendering";

import { ApiError, createSource } from "./data";
import { adjacency, pathEdges, RequestGeneration } from "./graph-utils";
import type { ColorBy, SizeBy } from "./encode";
import { buildContext, legend, nodeColor, nodeSize, nodeType } from "./encode";
import type { ActivityEvent, Details, Filters, GNode, GraphPayload, IndexEvent, Layer, Level } from "./types";
import { $, el, escapeHtml, toast } from "./ui";

// ---------------------------------------------------------------------------------------------
// State

const source = createSource();
const params = new URLSearchParams(location.search);
const KINDS = ["cluster", "package", "module", "class", "function", "method", "test", "route"];
const TRAIL_MS = 20_000;
const PULSE_MS = 2_500;

const emptyFilters = (): Filters => ({
  path: "", kinds: [], hide_tests: false, orphans_only: false, min_rank: 0, min_risk: 0, changed_since: "",
});

const state = {
  level: (params.get("level") as Level) || (params.get("focus") ? "file" : "package"),
  layer: "import" as Layer,
  root: params.get("focus") as string | null,
  depth: Number(params.get("depth") || 2),
  filters: emptyFilters(),
  colorBy: "group" as ColorBy,
  sizeBy: "rank" as SizeBy,
  selected: null as string | null,
  hovered: null as string | null,
  drill: null as string | null, // package being viewed at file level
  rings: null as Map<string, number> | null,
  path: null as Set<string> | null,
  pathEdges: new Set<string>(),
  diff: null as Map<string, string> | null,
  showCycles: true,
  showDead: false,
  showActivity: true,
  showLabels: true,
  trail: new Map<string, number>(),
  pulses: new Map<string, number>(),
  payload: null as GraphPayload | null,
  community: new Map<string, number>(),
  saved: {} as Record<string, [number, number]>,
};

const graph = new Graph({ type: "directed", multi: false, allowSelfLoops: false });
let layout: FA2Layout | null = null;
let layoutTimer: number | undefined;
let loadSeq = 0;
const searchRequests = new RequestGeneration();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let neighbors = new Map<string, Set<string>>();

// ---------------------------------------------------------------------------------------------
// Theme-aware colours

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
let palette = { edge: "", edgeWeak: "", label: "", faded: "", accent: "", danger: "", canvas: "" };
function readPalette(): void {
  palette = {
    edge: css("--edge"),
    edgeWeak: css("--edge-weak"),
    label: css("--label"),
    faded: document.documentElement.dataset.theme === "light" ? "#dfe2e8" : "#2a2e37",
    accent: css("--accent"),
    danger: css("--danger"),
    canvas: css("--canvas"),
  };
}
readPalette();

// ---------------------------------------------------------------------------------------------
// Renderer

const RING_COLORS = ["", "#e0607e", "#f2a33a", "#d4b13a", "#8fc24a"];
const DIFF_COLORS: Record<string, string> = { A: "#3fbf9f", M: "#f2a33a", D: "#e0607e", R: "#6c8cff" };

const renderer = new Sigma(graph, $("graph"), {
  nodeProgramClasses: {
    square: NodeSquareProgram,
    border: createNodeBorderProgram({
      borders: [
        { size: { value: 0.35 }, color: { attribute: "color" } },
        { size: { fill: true }, color: { attribute: "innerColor" } },
      ],
    }),
  },
  edgeProgramClasses: { arrow: EdgeArrowProgram },
  defaultEdgeType: "arrow",
  renderEdgeLabels: false,
  labelRenderedSizeThreshold: 7,
  labelDensity: 0.8,
  labelGridCellSize: 110,
  labelFont: "Inter, Segoe UI, system-ui, sans-serif",
  labelSize: 12,
  labelColor: { attribute: "labelColor" },
  defaultDrawNodeLabel: (ctx, data) => {
    if (!data.label) return;
    ctx.font = "500 12px Segoe UI, sans-serif";
    ctx.lineWidth = 4;
    ctx.lineJoin = "round";
    ctx.strokeStyle = palette.canvas;
    ctx.fillStyle = palette.label;
    const x = data.x + data.size + 7;
    ctx.strokeText(data.label, x, data.y + 4);
    ctx.fillText(data.label, x, data.y + 4);
  },
  defaultDrawNodeHover: (ctx, data) => {
    ctx.beginPath();
    ctx.arc(data.x, data.y, data.size + 5, 0, Math.PI * 2);
    ctx.strokeStyle = data.color;
    ctx.lineWidth = 1;
    ctx.stroke();
    if (!data.label) return;
    ctx.font = "600 12px Segoe UI, sans-serif";
    const width = ctx.measureText(data.label).width;
    ctx.fillStyle = palette.canvas;
    ctx.beginPath();
    ctx.roundRect(data.x + data.size + 8, data.y - 15, width + 20, 30, 7);
    ctx.fill();
    ctx.fillStyle = palette.label;
    ctx.fillText(data.label, data.x + data.size + 18, data.y + 4);
  },
  zIndex: true,
  allowInvalidContainer: true,
  minCameraRatio: 0.02,
  maxCameraRatio: 20,
  nodeReducer: (node, data) => {
    const res: Record<string, unknown> = { ...data, labelColor: palette.label };
    const now = performance.now();
    let faded = false;
    if (state.hovered && node !== state.hovered && !graph.areNeighbors(state.hovered, node)) faded = true;
    if (state.rings) {
      const d = state.rings.get(node);
      if (d !== undefined) res.color = RING_COLORS[Math.min(4, d)] || res.color;
      else if (node !== state.selected) faded = true;
    }
    if (state.path) {
      if (state.path.has(node)) res.highlighted = true;
      else faded = true;
    }
    if (state.diff) {
      const status = state.diff.get(node);
      if (status) res.color = DIFF_COLORS[status] ?? res.color;
      else faded = true;
    }
    if (state.showDead && data.dead) res.color = palette.danger;
    if (state.showActivity) {
      const t = state.trail.get(node);
      if (t !== undefined && now - t < TRAIL_MS) {
        res.highlighted = true;
        res.zIndex = 2;
        if (now - t < 4000) res.color = palette.accent;
      }
    }
    const p = state.pulses.get(node);
    if (p !== undefined && now - p < PULSE_MS) {
      const k = 1 - (now - p) / PULSE_MS;
      if (!reducedMotion.matches) {
        res.size = (data.size as number) * (1 + 0.9 * k * Math.abs(Math.sin((now - p) / 140)));
      }
      res.highlighted = true;
    }
    if (node === state.selected) {
      res.highlighted = true;
      res.zIndex = 3;
    }
    if (faded) {
      res.color = palette.faded;
      res.innerColor = palette.faded;
      res.label = "";
      res.zIndex = 0;
    }
    if (!state.showLabels && node !== state.selected && node !== state.hovered) res.label = "";
    return res;
  },
  edgeReducer: (edge, data) => {
    const res: Record<string, unknown> = { ...data };
    const [s, t] = graph.extremities(edge);
    res.color = data.confidence === "low" ? palette.edgeWeak : palette.edge;
    if (state.showCycles && data.cycle) res.color = palette.danger;
    if (state.hovered) {
      if (s !== state.hovered && t !== state.hovered) res.hidden = true;
      else res.color = palette.accent;
    }
    if (state.path) {
      if (state.pathEdges.has(JSON.stringify([s, t]))) {
        res.color = palette.accent;
        res.size = 2.5;
      } else res.hidden = true;
    }
    if (state.rings && !(state.rings.has(s) || s === state.selected) && !(state.rings.has(t) || t === state.selected)) {
      res.hidden = true;
    }
    if (state.diff && !state.diff.has(s) && !state.diff.has(t)) res.hidden = true;
    return res;
  },
});

let animating = false;
let animationTimer: number | undefined;
function animate(): void {
  if (animating && animationTimer === undefined) return;
  window.clearTimeout(animationTimer);
  animationTimer = undefined;
  animating = true;
  const tick = () => {
    const now = performance.now();
    for (const [id, t] of state.pulses) if (now - t > PULSE_MS) state.pulses.delete(id);
    for (const [id, t] of state.trail) if (now - t > TRAIL_MS) state.trail.delete(id);
    renderer.refresh({ skipIndexation: true });
    if (state.pulses.size && !reducedMotion.matches && !document.hidden) requestAnimationFrame(tick);
    else if (state.pulses.size || state.trail.size) {
      const boundaries = [
        ...[...state.pulses.values()].map((t) => t + PULSE_MS + 1),
        ...[...state.trail.values()].flatMap((t) => [t + 4001, t + TRAIL_MS + 1]),
      ].filter((t) => t > now);
      animationTimer = window.setTimeout(() => {
        animationTimer = undefined;
        tick();
      }, Math.max(16, Math.min(...boundaries) - now));
    }
    else animating = false;
  };
  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------------------------------------
// Loading and encoding

function encode(): void {
  const nodes: GNode[] = graph.mapNodes((_, a) => a.data as GNode);
  const ctx = buildContext(nodes, state.community);
  graph.forEachNode((id, a) => {
    const n = a.data as GNode;
    const color = nodeColor(n, state.colorBy, ctx);
    graph.mergeNodeAttributes(id, {
      color,
      innerColor: ["cluster", "package", "test", "route"].includes(n.kind) ? palette.canvas : color,
      size: nodeSize(n, state.sizeBy, ctx),
      type: nodeType(n),
      dead: Boolean(n.dead),
    });
  });
  renderLegend(nodes, ctx);
}

function renderLegend(nodes: GNode[], ctx: ReturnType<typeof buildContext>): void {
  const items = legend(state.colorBy, nodes, ctx);
  const box = $("legend");
  box.innerHTML = "";
  const title = el("button", { class: "legend-title", title: "Show or hide the legend" }, ["Legend"]);
  title.addEventListener("click", () => {
    box.classList.toggle("collapsed");
    try {
      localStorage.setItem("prism-legend", box.classList.contains("collapsed") ? "0" : "1");
    } catch {
      /* ignore */
    }
  });
  box.append(title);
  for (const it of items) box.append(el("div", {}, [el("span", { class: "sw", style: `background:${it.color}` }), it.label]));
  box.append(el("hr"));
  box.append(el("div", {}, [el("span", { class: "sw sq", style: "background:var(--muted)" }), "module"]));
  box.append(el("div", {}, [el("span", { class: "sw" , style: "background:var(--muted)"}), "function / method"]));
  box.append(el("div", {}, [el("span", { class: "sw ring" }), "package / class / test / route"]));
  const relation = { import: "imports", call: "calls", tests: "test relation", cochange: "changes together", routes: "route relationship" }[state.layer];
  box.append(el("div", { class: "muted" }, [`Edges: ${relation} · faint = low confidence${state.layer === "import" && state.showCycles ? " · red = import cycle" : ""}`]));
  box.append(el("div", { class: "muted" }, [`Size: ${state.sizeBy} · larger = higher value`]));
}

function placeNode(id: string, n: GNode, previous: Map<string, { x: number; y: number }>): { x: number; y: number } {
  const saved = state.saved[id];
  if (saved) return { x: saved[0], y: saved[1] };
  const prev = previous.get(id);
  if (prev) return prev;
  // Near already-placed neighbours, so new nodes don't reshuffle the map.
  const pts: { x: number; y: number }[] = [];
  for (const other of neighbors.get(id) ?? []) {
    const pos = previous.get(other) ?? (state.saved[other] && { x: state.saved[other][0], y: state.saved[other][1] });
    if (pos) pts.push(pos);
  }
  const r = Math.sqrt(graph.order + 10) * 8;
  if (pts.length) {
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
    const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
    return { x: cx + (Math.random() - 0.5) * 6, y: cy + (Math.random() - 0.5) * 6 };
  }
  const h = [...(n.group || id)].reduce((a, c) => a + c.charCodeAt(0), 0);
  const angle = (h % 360) * (Math.PI / 180);
  return { x: Math.cos(angle) * r + (Math.random() - 0.5) * r * 0.5, y: Math.sin(angle) * r + (Math.random() - 0.5) * r * 0.5 };
}

async function load(opts: { keepCamera?: boolean; pulse?: Set<string> } = {}): Promise<void> {
  const seq = ++loadSeq;
  // Imports and co-change are file-level relations; at symbol level the call graph is the useful view.
  if (state.level === "symbol" && (state.layer === "import" || state.layer === "cochange")) state.layer = "call";
  let payload: GraphPayload;
  try {
    payload = await source.graph({
      level: state.level, layer: state.layer, root: state.root, depth: state.depth, filters: state.filters,
    });
  } catch (err) {
    if (seq !== loadSeq) return;
    showError(err);
    if (err instanceof ApiError && state.root) {
      state.root = null;
      return load(opts);
    }
    return;
  }
  if (seq !== loadSeq) return;
  state.payload = payload;
  state.hovered = null;
  neighbors = adjacency(payload.edges);
  const previous = new Map<string, { x: number; y: number }>();
  graph.forEachNode((id, a) => previous.set(id, { x: a.x, y: a.y }));
  const pinned = new Set(graph.filterNodes((_, a) => Boolean(a.fixed)));
  stopLayout();
  graph.clear();
  for (const n of payload.nodes) {
    const pos = placeNode(n.id, n, previous);
    graph.addNode(n.id, { ...pos, label: n.label, data: n, fixed: pinned.has(n.id) || undefined });
  }
  for (const e of payload.edges) {
    if (graph.hasNode(e.source) && graph.hasNode(e.target) && !graph.hasEdge(e.source, e.target)) {
      graph.addEdgeWithKey(e.id, e.source, e.target, {
        weight: e.weight, confidence: e.confidence, cycle: Boolean(e.cycle), size: Math.min(2.5, 0.45 + Math.log1p(e.weight) * 0.35),
      });
    }
  }
  state.community = new Map();
  if (state.colorBy === "community" && graph.size > 0 && payload.nodes.some((n) => n.community === undefined)) {
    try {
      const communities = louvain(graph, { getEdgeWeight: "weight" }) as Record<string, number>;
      state.community = new Map(Object.entries(communities));
    } catch {
      /* community detection is optional */
    }
  }
  encode();
  if (state.selected && !graph.hasNode(state.selected)) closePanel();
  opts.pulse?.forEach((id) => graph.hasNode(id) && state.pulses.set(id, performance.now()));
  if (opts.pulse?.size) animate();
  updateChrome();
  const fresh = payload.nodes.filter((n) => !previous.has(n.id) && !state.saved[n.id]).length;
  if (fresh > 0 && !$<HTMLInputElement>("ph-run").dataset.frozen) {
    startLayout(Math.min(12_000, 3000 + payload.nodes.length * 6));
  }
  if (!opts.keepCamera) renderer.getCamera().animatedReset({ duration: reducedMotion.matches ? 0 : 300 });
  if (state.root && graph.hasNode(state.root)) select(state.root, false);
}

function updateChrome(): void {
  const p = state.payload;
  if (!p) return;
  document.querySelectorAll<HTMLButtonElement>("#level button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.level === state.level)),
  );
  $<HTMLSelectElement>("layer").value = state.layer;
  $("counts").textContent =
    `${p.counts.nodes.toLocaleString()} nodes · ${p.counts.edges.toLocaleString()} edges` +
    (p.truncated ? ` · ${p.truncated.toLocaleString()} hidden (cap)` : "");
  const crumbs = $("breadcrumb");
  crumbs.innerHTML = "";
  if (state.drill || state.root) {
    crumbs.append(el("button", { onclick: () => { state.drill = null; state.root = null; state.filters.path = ""; syncFilterInputs(); setLevel("package"); } }, ["All packages"]));
    if (state.drill) crumbs.append(el("span", { class: "muted" }, ["›", ` ${state.drill}`]));
    if (state.root) crumbs.append(el("span", { class: "muted" }, ["› local graph of ", el("code", {}, [state.root]), ` (depth ${state.depth})`]));
  }
  $("local-info").textContent = state.root ? `Around ${state.root}` : "Select a node and press L.";
  const empty = $("empty");
  empty.hidden = p.nodes.length > 0;
  empty.textContent = p.nodes.length ? "" : "Nothing matches these filters. Try resetting them, or another layer.";
}

// ---------------------------------------------------------------------------------------------
// Layout

function fa2Settings() {
  return {
    gravity: Number($<HTMLInputElement>("ph-gravity").value),
    scalingRatio: Number($<HTMLInputElement>("ph-scaling").value),
    slowDown: Number($<HTMLInputElement>("ph-slow").value),
    edgeWeightInfluence: Number($<HTMLInputElement>("ph-weight").value),
    linLogMode: $<HTMLInputElement>("ph-linlog").checked,
    barnesHutOptimize: graph.order > 400,
    adjustSizes: false,
    // Strong gravity keeps disconnected nodes (e.g. empty __init__ modules) near the map.
    strongGravityMode: $<HTMLInputElement>("ph-strong").checked,
  };
}

function startLayout(durationMs?: number): void {
  stopLayout();
  if (graph.order === 0) return;
  layout = new FA2Layout(graph, { settings: fa2Settings(), getEdgeWeight: "weight" });
  layout.start();
  $<HTMLInputElement>("ph-run").checked = true;
  $("layout-state").textContent = "layout running…";
  if (durationMs) {
    layoutTimer = window.setTimeout(() => {
      stopLayout(true);
      renderer.getCamera().animatedReset({ duration: 400 });
    }, durationMs);
  }
}

function stopLayout(save = false): void {
  window.clearTimeout(layoutTimer);
  if (layout) {
    layout.kill();
    layout = null;
  }
  $<HTMLInputElement>("ph-run").checked = false;
  $("layout-state").textContent = "";
  if (save) saveLayout();
}

let saveTimer: number | undefined;
function saveLayout(): void {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    const positions: Record<string, [number, number]> = {};
    graph.forEachNode((id, a) => {
      positions[id] = [a.x, a.y];
      state.saved[id] = [a.x, a.y];
    });
    source.saveLayout(positions).catch(() => undefined);
  }, 400);
}

// ---------------------------------------------------------------------------------------------
// Interaction

let dragged: string | null = null;
let dragMoved = false;
renderer.on("enterNode", ({ node }) => {
  state.hovered = node;
  $("graph").style.cursor = "pointer";
  renderer.refresh({ skipIndexation: true });
});
renderer.on("leaveNode", () => {
  state.hovered = null;
  $("graph").style.cursor = "";
  renderer.refresh({ skipIndexation: true });
});
renderer.on("clickNode", ({ node }) => {
  if (!dragMoved) select(node, false);
});
renderer.on("doubleClickNode", ({ node, event }) => {
  event.preventSigmaDefault();
  const n = graph.getNodeAttribute(node, "data") as GNode;
  if (n.kind === "cluster") drillInto(n);
  else if (state.level === "file") {
    state.root = node;
    setLevel("symbol");
  }
});
renderer.on("clickStage", () => {
  if (!dragMoved) closePanel();
});
renderer.on("downNode", ({ node }) => {
  dragged = node;
  dragMoved = false;
  if (!renderer.getCustomBBox()) renderer.setCustomBBox(renderer.getBBox());
});
renderer.on("moveBody", ({ event }) => {
  if (!dragged) return;
  dragMoved = true;
  const pos = renderer.viewportToGraph(event);
  graph.mergeNodeAttributes(dragged, { x: pos.x, y: pos.y, fixed: true });
  event.preventSigmaDefault();
  event.original.preventDefault();
  event.original.stopPropagation();
});
const endDrag = () => {
  if (dragged && dragMoved) saveLayout();
  dragged = null;
  window.setTimeout(() => (dragMoved = false), 0);
};
renderer.on("upNode", endDrag);
renderer.on("upStage", endDrag);

function drillInto(n: GNode): void {
  state.drill = n.group;
  state.filters.path = n.dir ? (n.dir.endsWith(".py") ? n.dir : `${n.dir}/*`) : "";
  syncFilterInputs();
  setLevel("file");
}

function setLevel(level: Level): void {
  state.level = level;
  state.rings = null;
  state.path = null;
  state.diff = null;
  void load();
}

function focusCamera(node: string): void {
  const d = renderer.getNodeDisplayData(node);
  if (d) renderer.getCamera().animate({ x: d.x, y: d.y, ratio: Math.min(renderer.getCamera().ratio, 0.35) }, { duration: 450 });
}

async function select(node: string, moveCamera = true): Promise<void> {
  state.selected = node;
  renderer.refresh({ skipIndexation: true });
  if (moveCamera) focusCamera(node);
  const panel = $("panel");
  panel.hidden = false;
  const body = $("panel-body");
  body.innerHTML = `<p class="muted">Loading ${escapeHtml(node)}…</p>`;
  try {
    const details = await source.node(node);
    if (state.selected === node) renderPanel(node, details);
  } catch (err) {
    if (state.selected !== node) return;
    const n = graph.hasNode(node) ? (graph.getNodeAttribute(node, "data") as GNode) : null;
    body.innerHTML = "";
    body.append(el("h2", {}, [node]));
    if (n?.doc) body.append(el("p", {}, [n.doc]));
    body.append(el("p", { class: "muted" }, [err instanceof Error ? err.message : "No details available."]));
  }
}

function closePanel(): void {
  state.selected = null;
  $("panel").hidden = true;
  renderer.refresh({ skipIndexation: true });
}

function linkList(items: { id: string; meta?: string }[]): HTMLElement {
  const ul = el("ul", { class: "links" });
  for (const it of items) {
    const button = el("button", { type: "button", title: it.id }, [it.id, it.meta ? el("span", { class: "muted" }, [`  ${it.meta}`]) : ""]);
    const li = el("li", {}, [button]);
    button.addEventListener("click", () => jumpTo(it.id));
    ul.append(li);
  }
  return ul;
}

function jumpTo(ref: string): void {
  if (graph.hasNode(ref)) {
    void select(ref);
    return;
  }
  const n = graph.findNode((_, a) => (a.data as GNode).file === ref || (a.data as GNode).module === ref);
  if (n) void select(n);
  else {
    state.root = ref;
    void load();
  }
}

function editorLink(editor: { path: string; line: number }): string {
  const scheme = localStorage.getItem("prism-editor") ?? "vscode";
  const path = editor.path.startsWith("/") ? editor.path : `/${editor.path}`;
  if (scheme === "idea") return `idea://open?file=${encodeURIComponent(editor.path)}&line=${editor.line}`;
  return `${scheme}://file${encodeURI(path)}:${editor.line}`;
}

function renderPanel(node: string, d: Details): void {
  const body = $("panel-body");
  body.innerHTML = "";
  const n = graph.hasNode(node) ? (graph.getNodeAttribute(node, "data") as GNode) : null;
  if (d.kind === "cluster") {
    body.append(el("h2", {}, [d.group]), el("span", { class: "badge" }, ["package"]), el("span", { class: "badge" }, [`${d.files.length} files`]));
    const actions = el("div", { class: "actions" });
    if (n) actions.append(el("button", { onclick: () => drillInto(n) }, ["Drill in"]));
    body.append(actions);
    if (d.summary) body.append(el("h3", {}, ["Summary"]), el("pre", { class: "sig" }, [d.summary.replace(/<!--.*?-->\n?/g, "")]));
    body.append(el("h3", {}, ["Files"]), linkList(d.files.map((f: string) => ({ id: f }))));
    return;
  }
  if (d.kind === "route") {
    body.append(el("h2", {}, [`${d.method} ${d.path}`]), el("span", { class: "badge" }, [d.framework]));
    body.append(el("h3", {}, ["Handler"]), linkList([{ id: d.handler }]));
    return;
  }
  const pack = d.pack ?? {};
  const t = pack.target ?? {};
  body.append(el("h2", {}, [t.id ?? node]));
  const badges = el("div");
  badges.append(el("span", { class: "badge" }, [t.kind ?? n?.kind ?? ""]));
  if (d.dead) badges.append(el("span", { class: "badge warn" }, ["dead-code candidate"]));
  if (pack.open_findings?.length) badges.append(el("span", { class: "badge bad" }, [`${pack.open_findings.length} open findings`]));
  if (n?.change) badges.append(el("span", { class: "badge warn" }, [`changed (${n.change})`]));
  body.append(badges);
  const lines = t.lines ? `:${t.lines[0]}-${t.lines[1]}` : "";
  body.append(el("div", { class: "loc" }, [`${t.file}${lines}`]));
  if (t.signature) body.append(el("div", { class: "sig" }, [t.signature]));
  if (pack.summary) body.append(el("p", {}, [pack.summary]));

  const actions = el("div", { class: "actions" });
  if (d.editor) actions.append(el("a", { href: editorLink(d.editor), title: "Open in your editor" }, ["Open in editor"]));
  actions.append(
    el("button", { onclick: () => copy(d.context_command) }, ["Copy prism context"]),
    el("button", { onclick: () => { state.root = node; void load(); } }, ["Local graph"]),
    el("button", { onclick: () => void showBlast(node) }, ["Blast radius"]),
  );
  body.append(actions);

  if (pack.risk) {
    body.append(el("h3", {}, [`Risk ${Math.round(pack.risk.score * 100)}%`]));
    const bar = el("div", { class: "riskbar" }, [el("i", { style: `width:${Math.round(pack.risk.score * 100)}%` })]);
    body.append(bar);
    if (pack.risk.reasons?.length) body.append(el("ul", {}, pack.risk.reasons.map((r: string) => el("li", {}, [r]))));
  }
  if (d.findings?.length) {
    body.append(el("h3", {}, ["Open audit findings"]));
    for (const f of d.findings) body.append(el("div", { class: "finding" }, [el("b", {}, [`${f.id} · ${f.severity}`]), el("div", {}, [f.title])]));
  }
  const sections: [string, { id: string; meta?: string }[]][] = [
    ["Callers", (pack.callers ?? []).map((c: any) => ({ id: c.id, meta: `${c.file}:${c.line}` }))],
    ["Callees", (pack.callees ?? []).map((c: any) => ({ id: c.id, meta: c.file }))],
    ["Members", (pack.members ?? []).map((m: string) => ({ id: m }))],
    ["Symbols", (pack.symbols ?? []).map((s: any) => ({ id: s.id, meta: s.kind }))],
    ["Imports", (pack.imports ?? []).map((m: string) => ({ id: m }))],
    ["Imported by", (pack.imported_by ?? []).map((m: string) => ({ id: m }))],
    ["Tests", (pack.tests ?? []).map((m: string) => ({ id: m }))],
    ["Co-changed", (pack.co_changed ?? []).map((m: string) => ({ id: m }))],
  ];
  for (const [title, items] of sections) if (items.length) body.append(el("h3", {}, [title]), linkList(items));
  if (pack.blast_radius?.files) {
    body.append(el("h3", {}, [`Blast radius · ${pack.blast_radius.files} files`]), linkList(pack.blast_radius.top.map((f: string) => ({ id: f }))));
  }
  if (d.owners?.length || d.churn) {
    body.append(el("h3", {}, ["Git"]), el("p", { class: "muted" }, [`${d.churn ?? 0} commits · owners: ${(d.owners ?? []).join(", ") || "unknown"}`]));
  }
  if (d.smells?.length) {
    body.append(el("h3", {}, ["Static smells (leads, not findings)"]), el("ul", {}, d.smells.map((s: any) => el("li", {}, [`${s.kind} · line ${s.line} · ${s.detail}`]))));
  }
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied: ${text}`);
  } catch {
    toast(text);
  }
}

async function showBlast(node: string): Promise<void> {
  try {
    const r = await source.impact(node, state.level);
    state.rings = new Map(Object.entries(r.rings));
    state.path = null;
    state.diff = null;
    renderer.refresh({ skipIndexation: true });
    toast(`Blast radius: ${r.totals.files} files, ${r.totals.symbols} symbols` + (r.tests.length ? ` · ${r.tests.length} tests to run` : ""));
  } catch (err) {
    showError(err);
  }
}

function showError(err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  toast(message, true);
}

// ---------------------------------------------------------------------------------------------
// Search

let searchTimer: number | undefined;
let hits: { id: string; kind: string; node?: string | null; file?: string | null; snippet?: string }[] = [];
let active = 0;
const searchInput = $<HTMLInputElement>("search");
const results = $("search-results");

function renderHits(): void {
  results.innerHTML = "";
  results.hidden = hits.length === 0;
  searchInput.setAttribute("aria-expanded", String(hits.length > 0));
  if (hits[active]) searchInput.setAttribute("aria-activedescendant", `search-hit-${active}`);
  else searchInput.removeAttribute("aria-activedescendant");
  hits.forEach((h, i) => {
    const li = el("li", { id: `search-hit-${i}`, role: "option", "aria-selected": String(i === active) }, [
      el("span", { class: "hit-id" }, [h.id]),
      el("span", { class: "hit-meta" }, [`${h.kind}${h.file ? ` · ${h.file}` : ""}${h.snippet ? ` — ${h.snippet}` : ""}`]),
    ]);
    li.addEventListener("mousedown", (e) => {
      e.preventDefault();
      choose(h);
    });
    results.append(li);
  });
}

function choose(h: (typeof hits)[number]): void {
  searchRequests.next();
  window.clearTimeout(searchTimer);
  hits = [];
  renderHits();
  searchInput.blur();
  const target = h.node ?? h.id;
  if (graph.hasNode(target)) void select(target);
  else {
    state.root = h.id;
    void load();
  }
}

searchInput.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  const request = searchRequests.next();
  hits = [];
  renderHits();
  searchTimer = window.setTimeout(async () => {
    const q = searchInput.value.trim();
    if (!q) {
      hits = [];
      renderHits();
      return;
    }
    try {
      const found = await source.search(q, state.level);
      if (!searchRequests.current(request)) return;
      hits = found;
      active = 0;
      renderHits();
    } catch (err) {
      if (!searchRequests.current(request)) return;
      showError(err);
    }
  }, 150);
});
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") active = Math.min(hits.length - 1, active + 1);
  else if (e.key === "ArrowUp") active = Math.max(0, active - 1);
  else if (e.key === "Enter" && hits[active]) choose(hits[active]);
  else if (e.key === "Escape") {
    searchRequests.next();
    hits = [];
    renderHits();
    searchInput.blur();
    return;
  } else return;
  e.preventDefault();
  renderHits();
});
searchInput.addEventListener("blur", () => window.setTimeout(() => {
  if (document.activeElement === searchInput) return;
  searchRequests.next();
  hits = [];
  renderHits();
}, 120));

// ---------------------------------------------------------------------------------------------
// Controls

function syncFilterInputs(): void {
  const f = state.filters;
  $<HTMLInputElement>("f-path").value = f.path;
  $<HTMLInputElement>("f-hide-tests").checked = f.hide_tests;
  $<HTMLInputElement>("f-orphans").checked = f.orphans_only;
  $<HTMLInputElement>("f-rank").value = String(f.min_rank);
  $<HTMLInputElement>("f-risk").value = String(f.min_risk);
  $<HTMLInputElement>("f-changed").value = f.changed_since;
  $("f-rank-out").textContent = String(f.min_rank);
  $("f-risk-out").textContent = String(f.min_risk);
  document.querySelectorAll<HTMLInputElement>("#f-kinds input").forEach((i) => (i.checked = f.kinds.includes(i.value)));
}

function readFilters(): void {
  state.filters = {
    path: $<HTMLInputElement>("f-path").value.trim(),
    kinds: [...document.querySelectorAll<HTMLInputElement>("#f-kinds input:checked")].map((i) => i.value),
    hide_tests: $<HTMLInputElement>("f-hide-tests").checked,
    orphans_only: $<HTMLInputElement>("f-orphans").checked,
    min_rank: Number($<HTMLInputElement>("f-rank").value),
    min_risk: Number($<HTMLInputElement>("f-risk").value),
    changed_since: $<HTMLInputElement>("f-changed").value.trim(),
  };
}

function bindControls(): void {
  $("zoom-in").addEventListener("click", () => renderer.getCamera().animatedZoom({ duration: reducedMotion.matches ? 0 : 220 }));
  $("zoom-out").addEventListener("click", () => renderer.getCamera().animatedUnzoom({ duration: reducedMotion.matches ? 0 : 220 }));
  $("zoom-fit").addEventListener("click", () => renderer.getCamera().animatedReset({ duration: reducedMotion.matches ? 0 : 300 }));
  const kinds = $("f-kinds");
  for (const k of KINDS) kinds.append(el("label", {}, [el("input", { type: "checkbox", value: k }), k]));
  document.querySelectorAll<HTMLButtonElement>("#level button").forEach((b) =>
    b.addEventListener("click", () => {
      state.drill = null;
      if (b.dataset.level === "package") state.filters.path = "";
      syncFilterInputs();
      setLevel(b.dataset.level as Level);
    }),
  );
  $<HTMLSelectElement>("layer").addEventListener("change", (e) => {
    state.layer = (e.target as HTMLSelectElement).value as Layer;
    void load();
  });
  $<HTMLSelectElement>("color-by").addEventListener("change", (e) => {
    state.colorBy = (e.target as HTMLSelectElement).value as ColorBy;
    if (state.colorBy === "community" && !state.community.size && graph.size > 0 && state.payload?.nodes.some((n) => n.community === undefined)) {
      state.community = new Map(Object.entries(louvain(graph, { getEdgeWeight: "weight" }) as Record<string, number>));
    }
    encode();
    renderer.refresh();
  });
  $<HTMLSelectElement>("size-by").addEventListener("change", (e) => {
    state.sizeBy = (e.target as HTMLSelectElement).value as SizeBy;
    encode();
    renderer.refresh();
  });
  for (const id of ["f-rank", "f-risk"]) {
    $<HTMLInputElement>(id).addEventListener("input", (e) => ($(`${id}-out`).textContent = (e.target as HTMLInputElement).value));
  }
  $("f-apply").addEventListener("click", () => {
    readFilters();
    void load();
  });
  for (const id of ["f-hide-tests", "f-orphans"]) $(id).addEventListener("change", () => (readFilters(), void load()));
  $("f-path").addEventListener("keydown", (e) => (e as KeyboardEvent).key === "Enter" && (readFilters(), void load()));
  $("f-reset").addEventListener("click", () => {
    state.filters = emptyFilters();
    state.drill = null;
    syncFilterInputs();
    void load();
  });
  $<HTMLInputElement>("depth").addEventListener("input", (e) => {
    state.depth = Number((e.target as HTMLInputElement).value);
    $("depth-out").textContent = String(state.depth);
    if (state.root) void load({ keepCamera: true });
  });
  $("local-clear").addEventListener("click", () => {
    state.root = null;
    void load();
  });
  const toggles: [string, (v: boolean) => void][] = [
    ["o-cycles", (v) => (state.showCycles = v)],
    ["o-dead", (v) => (state.showDead = v)],
    ["o-activity", (v) => (state.showActivity = v)],
    ["o-labels", (v) => (state.showLabels = v)],
  ];
  for (const [id, set] of toggles) {
    $<HTMLInputElement>(id).addEventListener("change", (e) => {
      set((e.target as HTMLInputElement).checked);
      renderer.refresh({ skipIndexation: true });
    });
  }
  $("o-diff-go").addEventListener("click", () => void showDiff($<HTMLInputElement>("o-diff").value.trim()));
  $("o-clear").addEventListener("click", clearOverlays);
  $("p-go").addEventListener("click", () => void findPath());
  $<HTMLInputElement>("ph-run").addEventListener("change", (e) => {
    const on = (e.target as HTMLInputElement).checked;
    if (on) startLayout();
    else stopLayout(true);
  });
  for (const id of ["ph-gravity", "ph-scaling", "ph-weight", "ph-slow"]) {
    $<HTMLInputElement>(id).addEventListener("input", (e) => {
      $(`${id}-out`).textContent = (e.target as HTMLInputElement).value;
      if (layout) startLayout();
    });
  }
  $("ph-linlog").addEventListener("change", () => layout && startLayout());
  $("ph-strong").addEventListener("change", () => layout && startLayout());
  $("ph-reset").addEventListener("click", () => {
    const r = Math.sqrt(graph.order + 10) * 8;
    graph.forEachNode((id) => graph.mergeNodeAttributes(id, { x: (Math.random() - 0.5) * r, y: (Math.random() - 0.5) * r, fixed: undefined }));
    state.saved = {};
    startLayout(Math.min(15_000, 2000 + graph.order * 8));
  });
  $("ph-unpin").addEventListener("click", () => graph.forEachNode((id) => graph.removeNodeAttribute(id, "fixed")));
  $("v-save").addEventListener("click", () => void saveView());
  $("panel-close").addEventListener("click", closePanel);
  $("toggle-sidebar").addEventListener("click", () => $("sidebar").classList.toggle("collapsed"));
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
    try {
      localStorage.setItem("prism-theme", root.dataset.theme);
    } catch {
      /* ignore */
    }
    readPalette();
    encode();
    renderer.refresh();
  });
  $("help").addEventListener("click", () => $<HTMLDialogElement>("help-dialog").showModal());

  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const typing = target instanceof Element && target.matches("input, select, textarea");
    if (e.key === "/" && !typing) {
      e.preventDefault();
      searchInput.focus();
      return;
    }
    if (typing) return;
    if (e.key === "Escape") {
      clearOverlays();
      closePanel();
    } else if ((e.key === "l" || e.key === "L") && state.selected) {
      state.root = state.selected;
      void load();
    } else if ((e.key === "b" || e.key === "B") && state.selected) {
      void showBlast(state.selected);
    } else if (e.key === "1") setLevel("package");
    else if (e.key === "2") setLevel("file");
    else if (e.key === "3") setLevel("symbol");
    else if (e.key === " ") {
      e.preventDefault();
      if (layout) stopLayout(true);
      else startLayout();
    }
  });
}

function clearOverlays(): void {
  state.rings = null;
  state.path = null;
  state.diff = null;
  $("p-info").textContent = "";
  renderer.refresh({ skipIndexation: true });
}

async function showDiff(since: string): Promise<void> {
  if (!since) return;
  try {
    const d = await source.diff(since);
    const map = new Map<string, string>();
    graph.forEachNode((id, a) => {
      const n = a.data as GNode;
      if (n.file && d.files[n.file]) map.set(id, d.files[n.file]);
      if (d.changed_ids.includes(id)) map.set(id, map.get(id) ?? "M");
      if (n.kind === "cluster") {
        const hit = Object.keys(d.files).some((f) => n.dir && f.startsWith(n.dir));
        if (hit) map.set(id, "M");
      }
    });
    state.diff = map;
    state.rings = null;
    state.path = null;
    renderer.refresh({ skipIndexation: true });
    toast(`${map.size} nodes changed since ${since}` + (Object.values(d.files).includes("D") ? " (deleted files are not drawn)" : ""));
  } catch (err) {
    showError(err);
  }
}

async function findPath(): Promise<void> {
  const from = $<HTMLInputElement>("p-from").value.trim();
  const to = $<HTMLInputElement>("p-to").value.trim();
  if (!from || !to) return;
  try {
    const r = await source.path(from, to, state.layer === "routes" ? "import" : state.layer, state.level);
    if (!r.nodes.length) {
      state.path = null;
      state.pathEdges.clear();
      renderer.refresh({ skipIndexation: true });
      $("p-info").textContent = "No path between these nodes in this layer.";
      return;
    }
    state.path = new Set(r.nodes);
    state.pathEdges = pathEdges(r.nodes, r.directed);
    state.rings = null;
    state.diff = null;
    $("p-info").textContent = `${r.nodes.length - 1} hops${r.directed ? "" : " (ignoring direction)"}: ${r.nodes.join(" → ")}`;
    renderer.refresh({ skipIndexation: true });
  } catch (err) {
    showError(err);
  }
}

async function saveView(): Promise<void> {
  const name = $<HTMLInputElement>("v-name").value.trim();
  if (!name) return;
  const cam = renderer.getCamera().getState();
  const view = {
    level: state.level, layer: state.layer, root: state.root, depth: state.depth, filters: state.filters,
    colorBy: state.colorBy, sizeBy: state.sizeBy, drill: state.drill, camera: cam,
  };
  try {
    await source.saveView(name, view);
    toast(`Saved view "${name}"`);
    await renderViews();
  } catch (err) {
    showError(err);
  }
}

async function renderViews(): Promise<void> {
  const list = $("v-list");
  list.innerHTML = "";
  const views = await source.views().catch(() => ({}));
  for (const [name, v] of Object.entries(views)) {
    list.append(el("li", {}, [el("button", { onclick: () => void applyView(v as any) }, [name])]));
  }
}

async function applyView(v: any): Promise<void> {
  Object.assign(state, {
    level: v.level, layer: v.layer, root: v.root, depth: v.depth, filters: { ...emptyFilters(), ...v.filters },
    colorBy: v.colorBy, sizeBy: v.sizeBy, drill: v.drill ?? null,
  });
  $<HTMLSelectElement>("color-by").value = state.colorBy;
  $<HTMLSelectElement>("size-by").value = state.sizeBy;
  syncFilterInputs();
  await load({ keepCamera: true });
  if (v.camera) renderer.getCamera().animate(v.camera, { duration: 400 });
}

// ---------------------------------------------------------------------------------------------
// Live updates

function mapToNode(ref: string): string | null {
  if (graph.hasNode(ref)) return ref;
  let found: string | null = null;
  graph.someNode((id, a) => {
    const n = a.data as GNode;
    if (n.file === ref || (n.module && (ref === n.module || ref.startsWith(`${n.module}.`)) && state.level !== "symbol")) {
      found = id;
      return true;
    }
    return false;
  });
  return found;
}

function onIndex(e: IndexEvent): void {
  const touched = new Set([...e.added, ...e.changed]);
  const pulse = new Set<string>();
  void load({ keepCamera: true }).then(() => {
    for (const ref of touched) {
      const id = mapToNode(ref);
      if (id) pulse.add(id);
    }
    pulse.forEach((id) => state.pulses.set(id, performance.now()));
    if (pulse.size) animate();
    toast(`Index updated · ${e.changed.length} changed, ${e.added.length} added, ${e.removed.length} removed`);
  });
}

function onActivity(e: ActivityEvent): void {
  if (!state.showActivity) return;
  const now = performance.now();
  for (const ref of e.ids) {
    const id = mapToNode(ref);
    if (id) state.trail.set(id, now);
  }
  animate();
  $("layout-state").textContent = `agent: ${e.op} ${e.ids.slice(0, 2).join(", ")}`;
}

// ---------------------------------------------------------------------------------------------
// Boot

async function boot(): Promise<void> {
  try {
    const saved = localStorage.getItem("prism-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch {
    /* ignore */
  }
  readPalette();
  try {
    if (localStorage.getItem("prism-legend") === "0") $("legend").classList.add("collapsed");
  } catch {
    /* ignore */
  }
  bindControls();
  if (matchMedia("(max-width: 900px)").matches) {
    $("sidebar").classList.add("collapsed");
    $("legend").classList.add("collapsed");
  }
  syncFilterInputs();
  $<HTMLInputElement>("depth").value = String(state.depth);
  $("depth-out").textContent = String(state.depth);
  try {
    const meta = await source.meta();
    $("project").textContent = meta.project;
    document.title = `${meta.project} · PRISM Graph`;
    $("scan-info").textContent = meta.last_scan ? `index ${meta.last_scan}` : "";
    if (!meta.has_routes) $<HTMLOptionElement>("layer").querySelector('option[value="routes"]')?.setAttribute("disabled", "");
    if (!meta.git) $<HTMLOptionElement>("layer").querySelector('option[value="cochange"]')?.setAttribute("disabled", "");
  } catch (err) {
    showError(err);
  }
  state.saved = await source.layout().catch(() => ({}));
  if (!source.live) {
    for (const id of ["f-changed", "o-diff", "o-diff-go"]) $<HTMLInputElement>(id).disabled = true;
  }
  await load();
  await renderViews();
  source.subscribe(onIndex, onActivity, (ok) => {
    $("live").classList.toggle("on", ok);
    $("live-text").textContent = source.live ? (ok ? "live" : "reconnecting…") : "static export";
  });
}

void boot();
