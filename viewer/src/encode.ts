// Visual encodings: node colour, size, and shape from node attributes, plus legends.
// Colours come from one spectrum (the "prism"), tuned separately for the dark and light canvas.
import type { GNode } from "./types";

export type ColorBy = "area" | "group" | "community" | "risk" | "owner" | "language" | "recency" | "findings" | "kind";
export type SizeBy = "rank" | "loc" | "fan_in" | "blast";
export type Theme = "dark" | "light";

export const COLOR_BY_LABELS: Record<ColorBy, string> = {
  area: "Area", group: "Package", community: "Community", risk: "Risk", findings: "Audit findings",
  owner: "Owner", recency: "Recency", kind: "Kind", language: "Language",
};
export const SIZE_BY_LABELS: Record<SizeBy, string> = {
  rank: "Importance", loc: "Lines of code", fan_in: "Fan-in", blast: "Blast radius",
};

// Twelve hues walked around the spectrum; lighter on dark, deeper on light, for contrast.
const SPECTRUM: Record<Theme, string[]> = {
  dark: [
    "#7b8cff", "#4cc9f0", "#5ee6a8", "#b5e655", "#ffe066", "#ffa45c",
    "#ff6b8b", "#f472d0", "#c77dff", "#6ea8ff", "#3dd6c6", "#e0a3ff",
  ],
  light: [
    "#4f5fe6", "#1486c2", "#10906f", "#5b8f1f", "#9c7a00", "#c96412",
    "#d6453d", "#c33a7f", "#8a47dc", "#2f6fd6", "#0a8a80", "#a24fcb",
  ],
};
const NEUTRAL_BY_THEME: Record<Theme, string> = { dark: "#7c849a", light: "#8a91a3" };
const HEAT: Record<Theme, [number, number, number][]> = {
  dark: [[111, 211, 176], [240, 212, 106], [255, 160, 90], [239, 110, 132]],
  light: [[16, 144, 111], [176, 140, 0], [214, 100, 20], [205, 50, 70]],
};
const RECENCY: Record<Theme, [number, number, number][]> = {
  dark: [[92, 100, 128], [92, 200, 245], [255, 176, 103]],
  light: [[150, 156, 172], [20, 134, 194], [201, 100, 18]],
};
const KIND_INDEX: Record<string, number> = {
  cluster: 0, package: 0, module: 1, class: 8, function: 2, method: 3, test: -1, route: 5,
};

export let NEUTRAL = NEUTRAL_BY_THEME.dark;
let theme: Theme = "dark";

export function setTheme(next: Theme): void {
  theme = next;
  NEUTRAL = NEUTRAL_BY_THEME[next];
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

export function paletteColor(i: number): string {
  const p = SPECTRUM[theme];
  return p[((i % p.length) + p.length) % p.length];
}

/**
 * Stable colours for a set of categories: sorted by size so the biggest groups get the
 * most distinct hues, then hashed for the long tail (so a group keeps its colour when
 * small groups come and go).
 */
export function categoricalScale(keys: Iterable<string>, counts?: Map<string, number>): Map<string, string> {
  const unique = [...new Set(keys)];
  unique.sort((a, b) => (counts?.get(b) ?? 0) - (counts?.get(a) ?? 0) || a.localeCompare(b));
  const out = new Map<string, string>();
  const n = SPECTRUM[theme].length;
  const used = new Set<number>();
  for (const key of unique) {
    let idx = hash(key) % n;
    if (used.size < n) {
      while (used.has(idx)) idx = (idx + 5) % n; // 5 is coprime with 12: visits every slot
      used.add(idx);
    }
    out.set(key, paletteColor(idx));
  }
  return out;
}

export function categorical(key: string | null | undefined): string {
  if (!key) return NEUTRAL;
  return paletteColor(hash(key));
}

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

function ramp(stops: [number, number, number][], t: number): string {
  const x = Math.max(0, Math.min(1, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const [a, b] = [stops[i], stops[i + 1]];
  return `rgb(${lerp(a[0], b[0], f)},${lerp(a[1], b[1], f)},${lerp(a[2], b[2], f)})`;
}

export function heat(t: number): string {
  return ramp(HEAT[theme], t);
}

export function kindColor(kind: string): string {
  const idx = KIND_INDEX[kind];
  return idx === undefined || idx < 0 ? NEUTRAL : paletteColor(idx);
}

export interface EncodeContext {
  maxLoc: number;
  maxRank: number;
  maxFanIn: number;
  maxBlast: number;
  newest: number;
  oldest: number;
  community: Map<string, number>;
  groups: Map<string, string>;
  areas: Map<string, string>;
  owners: Map<string, string>;
}

function max(values: number[], floor: number): number {
  let m = floor;
  for (const v of values) if (v > m) m = v;
  return m;
}

export function buildContext(nodes: GNode[], community: Map<string, number>): EncodeContext {
  const times = nodes.map((n) => n.last_changed ?? 0).filter((t) => t > 0);
  const groupCounts = new Map<string, number>();
  const areaCounts = new Map<string, number>();
  const ownerCounts = new Map<string, number>();
  for (const n of nodes) {
    groupCounts.set(n.group, (groupCounts.get(n.group) ?? 0) + 1);
    const area = areaOf(n);
    areaCounts.set(area, (areaCounts.get(area) ?? 0) + 1);
    if (n.owner) ownerCounts.set(n.owner, (ownerCounts.get(n.owner) ?? 0) + 1);
  }
  return {
    maxLoc: max(nodes.map((n) => n.loc), 1),
    maxRank: max(nodes.map((n) => n.rank), 1e-12),
    maxFanIn: max(nodes.map((n) => n.fan_in ?? 0), 1),
    maxBlast: max(nodes.map((n) => n.blast), 1),
    newest: times.length ? max(times, 0) : 0,
    oldest: times.length ? times.reduce((a, b) => Math.min(a, b)) : 0,
    community,
    groups: categoricalScale(groupCounts.keys(), groupCounts),
    areas: categoricalScale(areaCounts.keys(), areaCounts),
    owners: categoricalScale(ownerCounts.keys(), ownerCounts),
  };
}

/** The area a node belongs to (older indexes and exports have none: fall back to the group). */
export function areaOf(n: GNode): string {
  return n.area ?? n.group;
}

export function communityOf(n: GNode, ctx: EncodeContext): number | undefined {
  return n.community !== undefined && n.community >= 0 ? n.community : ctx.community.get(n.id);
}

export function nodeColor(n: GNode, by: ColorBy, ctx: EncodeContext): string {
  switch (by) {
    case "area":
      return ctx.areas.get(areaOf(n)) ?? categorical(areaOf(n));
    case "group":
      return ctx.groups.get(n.group) ?? categorical(n.group);
    case "community": {
      const c = communityOf(n, ctx);
      return c === undefined ? NEUTRAL : paletteColor(c);
    }
    case "risk":
      return heat(n.risk);
    case "owner":
      return n.owner ? ctx.owners.get(n.owner) ?? categorical(n.owner) : NEUTRAL;
    case "language":
      return categorical(n.language);
    case "recency": {
      if (!n.last_changed || ctx.newest === ctx.oldest) return NEUTRAL;
      return ramp(RECENCY[theme], (n.last_changed - ctx.oldest) / (ctx.newest - ctx.oldest));
    }
    case "findings":
      return n.findings ? heat(Math.min(1, 0.35 + n.findings * 0.25)) : NEUTRAL;
    case "kind":
      return kindColor(n.kind);
  }
}

export const MIN_NODE_SIZE = 4;
export const MAX_NODE_SIZE = 18;

export function sizeValue(n: GNode, by: SizeBy, ctx: EncodeContext): number {
  return by === "rank" ? n.rank / ctx.maxRank
    : by === "loc" ? n.loc / ctx.maxLoc
    : by === "fan_in" ? (n.fan_in ?? 0) / ctx.maxFanIn
    : n.blast / ctx.maxBlast;
}

export function nodeSize(n: GNode, by: SizeBy, ctx: EncodeContext): number {
  return MIN_NODE_SIZE + Math.sqrt(Math.max(0, sizeValue(n, by, ctx))) * (MAX_NODE_SIZE - MIN_NODE_SIZE);
}

export function nodeType(_n: GNode): "square" | "border" | "circle" {
  // As in Obsidian, every node is a plain dot; colour and the inspector say what it is.
  return "circle";
}

export interface LegendItem {
  color: string;
  label: string;
}

export function legend(by: ColorBy, nodes: GNode[], ctx: EncodeContext): LegendItem[] {
  if (by === "risk" || by === "findings") {
    return [
      { color: by === "risk" ? heat(0) : NEUTRAL, label: by === "risk" ? "Low risk" : "No findings" },
      { color: heat(0.5), label: "Medium" },
      { color: heat(1), label: by === "risk" ? "High risk" : "Many findings" },
    ];
  }
  if (by === "recency") {
    return [
      { color: ramp(RECENCY[theme], 0), label: "Changed long ago" },
      { color: ramp(RECENCY[theme], 1), label: "Changed recently" },
      { color: NEUTRAL, label: "No git history" },
    ];
  }
  if (by === "kind") {
    const kinds = [...new Set(nodes.map((n) => n.kind))].sort();
    return kinds.map((k) => ({ color: kindColor(k), label: k }));
  }
  const keyOf = (n: GNode): string =>
    by === "area" ? areaOf(n)
    : by === "group" ? n.group
    : by === "owner" ? n.owner ?? "Unknown owner"
    : by === "language" ? n.language
    : `Community ${communityOf(n, ctx) ?? "–"}`;
  const counts = new Map<string, { color: string; n: number }>();
  for (const n of nodes) {
    const key = keyOf(n);
    const entry = counts.get(key) ?? { color: nodeColor(n, by, ctx), n: 0 };
    entry.n++;
    counts.set(key, entry);
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0]));
  const shown = sorted.slice(0, 9).map(([label, v]) => ({ color: v.color, label: `${label} · ${v.n}` }));
  const rest = sorted.slice(9);
  if (rest.length) {
    shown.push({ color: NEUTRAL, label: `${rest.length} more · ${rest.reduce((s, [, v]) => s + v.n, 0)}` });
  }
  return shown;
}
