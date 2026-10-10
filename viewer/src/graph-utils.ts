// Pure graph helpers (no DOM): adjacency, path edges, request generations, seed layout,
// spatial keyboard navigation, and ranking. Unit-tested in tests/*.test.mjs.
import type { GEdge, GNode } from "./types";

/** Build once per payload instead of scanning every edge for each new node. */
export function adjacency(edges: Pick<GEdge, "source" | "target">[]): Map<string, Set<string>> {
  const result = new Map<string, Set<string>>();
  for (const { source, target } of edges) {
    if (!result.has(source)) result.set(source, new Set());
    if (!result.has(target)) result.set(target, new Set());
    result.get(source)!.add(target);
    result.get(target)!.add(source);
  }
  return result;
}

export interface Relations {
  incoming: Map<string, string[]>;
  outgoing: Map<string, string[]>;
}

/** Directed neighbour lists, for the inspector's "in this view" connections. */
export function relations(edges: Pick<GEdge, "source" | "target">[]): Relations {
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const { source, target } of edges) {
    (outgoing.get(source) ?? outgoing.set(source, []).get(source)!).push(target);
    (incoming.get(target) ?? incoming.set(target, []).get(target)!).push(source);
  }
  return { incoming, outgoing };
}

export function edgeKey(source: string, target: string): string {
  return `${source}\u0000${target}`;
}

export function pathEdges(nodes: string[], directed: boolean): Set<string> {
  const edges = new Set<string>();
  for (let i = 1; i < nodes.length; i++) {
    edges.add(edgeKey(nodes[i - 1], nodes[i]));
    if (!directed) edges.add(edgeKey(nodes[i], nodes[i - 1]));
  }
  return edges;
}

/** A generation also invalidates in-flight work when an input is cleared. */
export class RequestGeneration {
  private generation = 0;
  next(): number {
    return ++this.generation;
  }
  current(generation: number): boolean {
    return this.generation === generation;
  }
}

function hash01(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967296;
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/**
 * Deterministic structured starting positions: each group becomes a sunflower (phyllotaxis)
 * disc of its nodes, largest-first, and the groups themselves are laid out on a larger
 * sunflower. The graph is readable before the force layout runs, the force layout converges
 * in far fewer iterations, and the same data always starts in the same place.
 */
export function seedPositions(nodes: (Pick<GNode, "id" | "group" | "rank"> & { area?: string })[], spacing = 1): Map<string, { x: number; y: number }> {
  // Areas (or, without them, groups) start as neighbouring discs: what belongs together is together.
  const groups = new Map<string, Pick<GNode, "id" | "group" | "rank">[]>();
  for (const n of nodes) {
    const key = n.area ?? n.group;
    (groups.get(key) ?? groups.set(key, []).get(key)!).push(n);
  }
  const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  const out = new Map<string, { x: number; y: number }>();
  const step = 6 * spacing;
  let placedArea = 0;
  ordered.forEach(([, members], gi) => {
    members.sort((a, b) => b.rank - a.rank || a.id.localeCompare(b.id));
    const radius = step * Math.sqrt(members.length) + step;
    // Group centres spiral outward, spaced by the area already used.
    const centreDist = gi === 0 ? 0 : Math.sqrt(placedArea) * 1.15 + radius;
    const angle = gi * GOLDEN_ANGLE;
    const cx = Math.cos(angle) * centreDist;
    const cy = Math.sin(angle) * centreDist;
    placedArea += Math.PI * radius * radius;
    members.forEach((n, i) => {
      const r = step * Math.sqrt(i + 0.5);
      const a = i * GOLDEN_ANGLE + hash01(n.group) * Math.PI * 2;
      out.set(n.id, { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r });
    });
  });
  return out;
}

export type Direction = "up" | "down" | "left" | "right";

/**
 * Keyboard graph navigation: the best node in a direction, preferring close nodes that lie
 * near the direction's axis. Screen y grows downward.
 */
export function nearestInDirection(
  from: { x: number; y: number },
  candidates: Iterable<[string, { x: number; y: number }]>,
  direction: Direction,
): string | null {
  let best: string | null = null;
  let bestScore = Infinity;
  for (const [id, p] of candidates) {
    const dx = p.x - from.x;
    const dy = p.y - from.y;
    const along = direction === "right" ? dx : direction === "left" ? -dx : direction === "down" ? dy : -dy;
    const across = direction === "left" || direction === "right" ? Math.abs(dy) : Math.abs(dx);
    if (along <= 1e-9) continue;
    const score = along + across * 2.5;
    if (score < bestScore) {
      bestScore = score;
      best = id;
    }
  }
  return best;
}

/** Percentile rank (0–100) of `value` within `values`. */
export function percentile(values: number[], value: number): number {
  if (!values.length) return 0;
  let below = 0;
  for (const v of values) if (v < value) below++;
  return Math.round((below / values.length) * 100);
}

/** True when (more than two) points sit on top of each other: a layout that never unfolded. */
export function collapsed(points: [number, number][]): boolean {
  if (points.length < 3) return false;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const [x, y] of points) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return true;
    x0 = Math.min(x0, x); x1 = Math.max(x1, x);
    y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return x1 - x0 < 1e-3 && y1 - y0 < 1e-3;
}
