// Visual encodings: node colour, size, and shape from node attributes, plus legends.
import type { GNode } from "./types";

export type ColorBy = "group" | "community" | "risk" | "owner" | "language" | "recency" | "findings" | "kind";
export type SizeBy = "rank" | "loc" | "fan_in" | "blast";

// Categorical palette tuned to stay distinct on both the dark and the light canvas.
const CATEGORICAL = [
  "#8aa8ff", "#dfb579", "#69cbb3", "#dd8f9e", "#b1a0e8", "#a2be89",
  "#dca188", "#80bfd7", "#c5bc8b", "#bb9dcb", "#83bba2", "#d7a5ad",
];
export const NEUTRAL = "#8a93a6";

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return Math.abs(h);
}

export function categorical(key: string | null | undefined): string {
  if (!key) return NEUTRAL;
  return CATEGORICAL[hash(key) % CATEGORICAL.length];
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

const HEAT: [number, number, number][] = [[78, 173, 120], [226, 196, 72], [228, 108, 60], [214, 52, 72]];
const RECENCY: [number, number, number][] = [[98, 110, 140], [90, 150, 220], [240, 170, 60]];

export const KIND_COLORS: Record<string, string> = {
  cluster: "#6c8cff", package: "#6c8cff", module: "#3aa7d9", class: "#a67cf0",
  function: "#3fbf9f", method: "#8fc24a", test: "#8a93a6", route: "#f2a33a",
};

export interface EncodeContext {
  maxLoc: number;
  maxRank: number;
  maxFanIn: number;
  maxBlast: number;
  newest: number;
  oldest: number;
  community: Map<string, number>;
}

export function buildContext(nodes: GNode[], community: Map<string, number>): EncodeContext {
  const times = nodes.map((n) => n.last_changed ?? 0).filter((t) => t > 0);
  return {
    maxLoc: Math.max(1, ...nodes.map((n) => n.loc)),
    maxRank: Math.max(1e-12, ...nodes.map((n) => n.rank)),
    maxFanIn: Math.max(1, ...nodes.map((n) => n.fan_in ?? 0)),
    maxBlast: Math.max(1, ...nodes.map((n) => n.blast)),
    newest: times.length ? Math.max(...times) : 0,
    oldest: times.length ? Math.min(...times) : 0,
    community,
  };
}

export function nodeColor(n: GNode, by: ColorBy, ctx: EncodeContext): string {
  switch (by) {
    case "group":
      return categorical(n.group);
    case "community": {
      // Prefer the index's communities so the picture matches `prism` output; fall back to client-side Louvain.
      const c = n.community !== undefined && n.community >= 0 ? n.community : ctx.community.get(n.id);
      return c === undefined ? NEUTRAL : CATEGORICAL[c % CATEGORICAL.length];
    }
    case "risk":
      return ramp(HEAT, n.risk);
    case "owner":
      return categorical(n.owner);
    case "language":
      return categorical(n.language);
    case "recency": {
      if (!n.last_changed || ctx.newest === ctx.oldest) return NEUTRAL;
      return ramp(RECENCY, (n.last_changed - ctx.oldest) / (ctx.newest - ctx.oldest));
    }
    case "findings":
      return n.findings ? ramp(HEAT, Math.min(1, 0.35 + n.findings * 0.25)) : NEUTRAL;
    case "kind":
      return KIND_COLORS[n.kind] ?? NEUTRAL;
  }
}

export function nodeSize(n: GNode, by: SizeBy, ctx: EncodeContext): number {
  const t =
    by === "rank" ? n.rank / ctx.maxRank
    : by === "loc" ? n.loc / ctx.maxLoc
    : by === "fan_in" ? (n.fan_in ?? 0) / ctx.maxFanIn
    : n.blast / ctx.maxBlast;
  return 3 + Math.sqrt(Math.max(0, t)) * 12;
}

export function nodeType(n: GNode): string {
  if (n.kind === "cluster" || n.kind === "package") return "border";
  if (n.kind === "module") return "square";
  if (n.kind === "test" || n.kind === "route" || n.kind === "class") return "border";
  return "circle";
}

export interface LegendItem {
  color: string;
  label: string;
}

export function legend(by: ColorBy, nodes: GNode[], ctx: EncodeContext): LegendItem[] {
  if (by === "risk" || by === "findings") {
    return [
      { color: by === "risk" ? ramp(HEAT, 0) : NEUTRAL, label: by === "risk" ? "low risk" : "no findings" },
      { color: ramp(HEAT, 0.5), label: "medium" },
      { color: ramp(HEAT, 1), label: by === "risk" ? "high risk" : "many findings" },
    ];
  }
  if (by === "recency") {
    return [
      { color: ramp(RECENCY, 0), label: "changed long ago" },
      { color: ramp(RECENCY, 1), label: "changed recently" },
      { color: NEUTRAL, label: "no git history" },
    ];
  }
  if (by === "kind") {
    const kinds = [...new Set(nodes.map((n) => n.kind))].sort();
    return kinds.map((k) => ({ color: KIND_COLORS[k] ?? NEUTRAL, label: k }));
  }
  const keyOf = (n: GNode): string =>
    by === "group" ? n.group : by === "owner" ? n.owner ?? "unknown" : by === "language" ? n.language
    : `community ${n.community !== undefined && n.community >= 0 ? n.community : ctx.community.get(n.id) ?? "-"}`;
  const counts = new Map<string, { color: string; n: number }>();
  for (const n of nodes) {
    const key = keyOf(n);
    const entry = counts.get(key) ?? { color: nodeColor(n, by, ctx), n: 0 };
    entry.n++;
    counts.set(key, entry);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1].n - a[1].n)
    .slice(0, 10)
    .map(([label, v]) => ({ color: v.color, label: `${label} (${v.n})` }));
}
