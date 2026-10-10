// Overview: what this view says about the code, before anyone clicks. Computed from the loaded
// graph only (so it works in static exports too): the shape (areas, tiers), the code everything
// leans on, cycles, the riskiest code, entry points, and what is not connected at all.
import type { App } from "./app";
import { KIND_LABELS, LEVEL_LABELS } from "./app";
import { areaOf } from "./encode";
import type { GEdge, GNode } from "./types";
import { $, el, plural } from "./ui";

const TOP = 5;

export interface Insights {
  nodes: number;
  edges: number;
  tiers: number;
  areas: { name: string; count: number }[];
  hubs: GNode[];
  cycles: GNode[][];
  risky: GNode[];
  entries: GNode[];
  orphans: GNode[];
}

export function computeInsights(nodes: GNode[], edges: GEdge[], tiers: number): Insights {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  // Cycles: nodes joined by cycle edges, grouped with a union-find.
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let r = x;
    while (parent.get(r) !== r) r = parent.get(r)!;
    parent.set(x, r);
    return r;
  };
  for (const e of edges) {
    if (!e.cycle) continue;
    for (const id of [e.source, e.target]) if (!parent.has(id)) parent.set(id, id);
    parent.set(find(e.source), find(e.target));
  }
  const groups = new Map<string, GNode[]>();
  for (const id of parent.keys()) {
    const n = byId.get(id);
    if (n) (groups.get(find(id)) ?? groups.set(find(id), []).get(find(id))!).push(n);
  }
  const areaCounts = new Map<string, number>();
  for (const n of nodes) areaCounts.set(areaOf(n), (areaCounts.get(areaOf(n)) ?? 0) + 1);
  const code = nodes.filter((n) => !n.test);
  const byRank = (a: GNode, b: GNode) => b.rank - a.rank || a.id.localeCompare(b.id);
  return {
    nodes: nodes.length,
    edges: edges.length,
    tiers,
    areas: [...areaCounts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name)),
    hubs: code.filter((n) => (n.fan_in ?? 0) > 1).sort((a, b) => (b.fan_in ?? 0) - (a.fan_in ?? 0) || byRank(a, b)).slice(0, TOP),
    cycles: [...groups.values()].map((g) => g.sort(byRank)).sort((a, b) => b.length - a.length),
    risky: code.filter((n) => n.risk >= 0.5).sort((a, b) => b.risk - a.risk || byRank(a, b)).slice(0, TOP),
    entries: code
      .filter((n) => n.entry_point || (tiers > 2 && n.tier === tiers - 1 && (degree.get(n.id) ?? 0) > 0))
      .sort(byRank)
      .slice(0, TOP),
    orphans: nodes.filter((n) => !degree.has(n.id)).sort(byRank),
  };
}

function nodeButton(app: App, n: GNode, meta: string): HTMLElement {
  const color = app.graph.hasNode(n.id) ? (app.graph.getNodeAttribute(n.id, "color") as string) : "var(--dim)";
  const button = el("button", { type: "button", class: "ov-item", title: n.id }, [
    el("span", { class: "sw", style: `background:${color}`, "aria-hidden": "true" }),
    el("span", { class: "ov-name" }, [n.label]),
    el("span", { class: "ov-meta" }, [meta]),
  ]);
  button.addEventListener("click", () => app.select(n.id));
  button.addEventListener("mouseenter", () => {
    app.state.hovered = n.id;
    app.refresh();
  });
  button.addEventListener("mouseleave", () => {
    app.state.hovered = null;
    app.refresh();
  });
  return button;
}

function block(title: string, note: string, children: HTMLElement[]): HTMLElement {
  return el("section", { class: "ov-block" }, [
    el("h3", { class: "ov-title" }, [title]),
    el("p", { class: "ov-note" }, [note]),
    el("div", { class: "ov-list" }, children),
  ]);
}

export function renderOverview(app: App): void {
  const pane = $("pane-overview");
  const p = app.payload;
  if (!p) return;
  const nodesNoun = LEVEL_LABELS[app.state.level].toLowerCase();
  const ins = computeInsights(p.nodes, p.edges, p.tiers ?? 0);
  const ctx = app.encoding;
  const total = Math.max(1, ins.nodes);

  const figures = el("div", { class: "ov-figures" }, [
    figure(ins.nodes, nodesNoun.replace(/s$/, ""), nodesNoun),
    figure(ins.edges, "link", "links"),
    ins.tiers ? figure(ins.tiers, "tier", "tiers") : figure(ins.areas.length, "area", "areas"),
  ]);

  // The spectrum of the codebase: one bar, one segment per area, in its colour.
  const bar = el("div", { class: "ov-spectrum", role: "img", "aria-label": `Areas: ${ins.areas.slice(0, 6).map((a) => `${a.name} ${a.count}`).join(", ")}` });
  for (const a of ins.areas) {
    const color = ctx?.areas.get(a.name) ?? "var(--dim)";
    bar.append(el("i", { style: `flex:${a.count} 0 0;background:${color}`, title: `${a.name} · ${plural(a.count, nodesNoun.replace(/s$/, ""), nodesNoun)}` }));
  }
  const areaList = el("ul", { class: "ov-areas" }, ins.areas.slice(0, 8).map((a) =>
    el("li", {}, [
      el("span", { class: "sw", style: `background:${ctx?.areas.get(a.name) ?? "var(--dim)"}`, "aria-hidden": "true" }),
      el("span", { class: "ov-area-name" }, [a.name]),
      el("span", { class: "ov-area-n" }, [`${Math.round((a.count / total) * 100)}%`]),
    ]),
  ));

  const blocks: HTMLElement[] = [];
  if (ins.hubs.length) {
    blocks.push(block("Load-bearing", "Most depended on: changes here ripple furthest.",
      ins.hubs.map((n) => nodeButton(app, n, `${n.fan_in} in`))));
  }
  if (ins.cycles.length) {
    blocks.push(block(
      `${plural(ins.cycles.length, "cycle")}`,
      "Code that depends on itself in a loop: hard to change or test in isolation.",
      ins.cycles.slice(0, TOP).map((g) => nodeButton(app, g[0], g.length > 1 ? `with ${g.slice(1, 3).map((n) => n.label).join(", ")}${g.length > 3 ? ` +${g.length - 3}` : ""}` : "")),
    ));
  }
  if (ins.risky.length) {
    blocks.push(block("Riskiest", "Complex, often changed, central or poorly tested.",
      ins.risky.map((n) => nodeButton(app, n, `${Math.round(n.risk * 100)}% risk`))));
  }
  if (ins.entries.length) {
    blocks.push(block("Entry points", "Where execution starts, or the top of the dependency stack.",
      ins.entries.map((n) => nodeButton(app, n, n.entry_point ? String(n.entry_point) : KIND_LABELS[n.kind] ?? n.kind))));
  }
  if (ins.orphans.length) {
    blocks.push(block(`${plural(ins.orphans.length, "unconnected node")}`, "Nothing in this view links to or from these. Possibly unused, or connected another way.",
      ins.orphans.slice(0, TOP).map((n) => nodeButton(app, n, KIND_LABELS[n.kind] ?? n.kind))));
  }
  pane.replaceChildren(
    el("div", { class: "ov-head" }, [figures, bar, areaList]),
    ...blocks,
  );
}

function figure(n: number, one: string, many: string): HTMLElement {
  return el("div", { class: "ov-figure" }, [el("b", {}, [n.toLocaleString()]), el("span", {}, [n === 1 ? one : many])]);
}
