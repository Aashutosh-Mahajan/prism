import type { GEdge } from "./types";

/** Build once per payload instead of scanning every edge for each new node. */
export function adjacency(edges: GEdge[]): Map<string, Set<string>> {
  const result = new Map<string, Set<string>>();
  for (const { source, target } of edges) {
    if (!result.has(source)) result.set(source, new Set());
    if (!result.has(target)) result.set(target, new Set());
    result.get(source)!.add(target);
    result.get(target)!.add(source);
  }
  return result;
}

export function pathEdges(nodes: string[], directed: boolean): Set<string> {
  const edges = new Set<string>();
  for (let i = 1; i < nodes.length; i++) {
    edges.add(JSON.stringify([nodes[i - 1], nodes[i]]));
    if (!directed) edges.add(JSON.stringify([nodes[i], nodes[i - 1]]));
  }
  return edges;
}

/** A generation also invalidates in-flight work when an input is cleared. */
export class RequestGeneration {
  private generation = 0;
  next(): number { return ++this.generation; }
  current(generation: number): boolean { return this.generation === generation; }
}
