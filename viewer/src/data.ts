// Data sources: the local PRISM server (`prism view`) or data embedded by `prism graph export --html`.
import type {
  ActivityEvent,
  Details,
  GEdge,
  GNode,
  GraphPayload,
  GraphQuery,
  ImpactResult,
  IndexEvent,
  Meta,
  PathResult,
  SearchHit,
} from "./types";

export interface DataSource {
  readonly live: boolean;
  meta(): Promise<Meta>;
  graph(q: GraphQuery): Promise<GraphPayload>;
  node(id: string): Promise<Details>;
  search(q: string, level: string): Promise<SearchHit[]>;
  path(from: string, to: string, layer: string, level: string): Promise<PathResult>;
  impact(id: string, level: string): Promise<ImpactResult>;
  diff(since: string): Promise<{ files: Record<string, string>; changed_ids: string[] }>;
  layout(): Promise<Record<string, [number, number]>>;
  saveLayout(positions: Record<string, [number, number]>): Promise<void>;
  views(): Promise<Record<string, unknown>>;
  saveView(name: string, state: unknown): Promise<void>;
  subscribe(onIndex: (e: IndexEvent) => void, onActivity: (e: ActivityEvent) => void, onStatus: (ok: boolean) => void): void;
}

export class ApiError extends Error {
  constructor(message: string, public readonly payload: Record<string, unknown>) {
    super(message);
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: "same-origin" });
  const body = await res.json();
  if (!res.ok) throw new ApiError(String(body.message ?? res.statusText), body);
  return body as T;
}

async function postJson(url: string, body: unknown): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError("save failed", await res.json().catch(() => ({})));
}

function queryString(q: GraphQuery): string {
  const p = new URLSearchParams({ level: q.level, layer: q.layer, depth: String(q.depth) });
  if (q.root) p.set("root", q.root);
  const f = q.filters;
  if (f.path) p.set("path", f.path);
  if (f.kinds.length) p.set("kinds", f.kinds.join(","));
  if (f.hide_tests) p.set("hide_tests", "1");
  if (f.orphans_only) p.set("orphans_only", "1");
  if (f.min_rank) p.set("min_rank", String(f.min_rank));
  if (f.min_risk) p.set("min_risk", String(f.min_risk));
  if (f.changed_since) p.set("changed_since", f.changed_since);
  return p.toString();
}

export class HttpSource implements DataSource {
  readonly live = true;
  meta() {
    return getJson<Meta>("/api/meta");
  }
  graph(q: GraphQuery) {
    return getJson<GraphPayload>(`/api/graph?${queryString(q)}`);
  }
  node(id: string) {
    return getJson<Details>(`/api/node/${encodeURIComponent(id)}`);
  }
  async search(q: string, level: string) {
    const r = await getJson<{ hits: SearchHit[] }>(`/api/search?q=${encodeURIComponent(q)}&level=${level}`);
    return r.hits;
  }
  path(from: string, to: string, layer: string, level: string) {
    const p = new URLSearchParams({ from, to, layer, level });
    return getJson<PathResult>(`/api/path?${p}`);
  }
  impact(id: string, level: string) {
    return getJson<ImpactResult>(`/api/impact/${encodeURIComponent(id)}?level=${level}`);
  }
  diff(since: string) {
    return getJson<{ files: Record<string, string>; changed_ids: string[] }>(`/api/diff?since=${encodeURIComponent(since)}`);
  }
  async layout() {
    const r = await getJson<{ positions?: Record<string, [number, number]> }>("/api/layout");
    return r.positions ?? {};
  }
  saveLayout(positions: Record<string, [number, number]>) {
    return postJson("/api/layout", { positions });
  }
  async views() {
    return (await getJson<{ views: Record<string, unknown> }>("/api/views")).views;
  }
  saveView(name: string, state: unknown) {
    return postJson("/api/views", { name, state });
  }
  subscribe(onIndex: (e: IndexEvent) => void, onActivity: (e: ActivityEvent) => void, onStatus: (ok: boolean) => void) {
    const es = new EventSource("/api/events");
    es.addEventListener("open", () => onStatus(true));
    es.addEventListener("error", () => onStatus(false));
    es.addEventListener("index", (e) => onIndex(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("activity", (e) => onActivity(JSON.parse((e as MessageEvent).data)));
  }
}

// ---------------------------------------------------------------------------------------------
// Static export: everything precomputed by `prism graph export --html`. Graph *display* logic
// (local neighbourhood, path, impact rings) runs on the embedded graph; nothing leaves the file.

interface StaticBundle {
  meta: Meta;
  graphs: Record<string, GraphPayload>;
  details: Record<string, Details>;
}

declare global {
  interface Window {
    __PRISM_STATIC__?: StaticBundle;
  }
}

function neighbourhood(edges: GEdge[], root: string, depth: number, directed = false): Map<string, number> {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    (adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target);
    if (!directed) (adj.get(e.target) ?? adj.set(e.target, []).get(e.target)!).push(e.source);
  }
  const dist = new Map([[root, 0]]);
  const queue = [root];
  while (queue.length) {
    const cur = queue.shift()!;
    const d = dist.get(cur)!;
    if (d >= depth) continue;
    for (const n of adj.get(cur) ?? []) {
      if (!dist.has(n)) {
        dist.set(n, d + 1);
        queue.push(n);
      }
    }
  }
  return dist;
}

function globToRegExp(glob: string): RegExp {
  const esc = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${esc}$`);
}

export class StaticSource implements DataSource {
  readonly live = false;
  constructor(private readonly bundle: StaticBundle) {}

  async meta() {
    return { ...this.bundle.meta, static: true };
  }

  private base(level: string, layer: string): GraphPayload {
    const g = this.bundle.graphs[`${level}|${layer}`] ?? this.bundle.graphs[`${level}|import`];
    if (!g) throw new ApiError(`no ${level}-level ${layer} graph in this export`, {});
    return g;
  }

  async graph(q: GraphQuery) {
    const g = this.base(q.level, q.layer);
    const f = q.filters;
    const maxRank = Math.max(1e-12, ...g.nodes.map((n) => n.rank));
    const re = f.path ? globToRegExp(f.path) : null;
    let nodes: GNode[] = g.nodes.filter(
      (n) =>
        !(f.hide_tests && n.test) &&
        !(f.kinds.length && !f.kinds.includes(n.kind)) &&
        !(re && !(n.file && re.test(n.file))) &&
        n.rank / maxRank >= f.min_rank &&
        n.risk >= f.min_risk,
    );
    let ids = new Set(nodes.map((n) => n.id));
    let edges = g.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    if (q.root && ids.has(q.root)) {
      const near = neighbourhood(edges, q.root, q.depth);
      nodes = nodes.filter((n) => near.has(n.id)).map((n) => ({ ...n, distance: near.get(n.id) }));
      ids = new Set(nodes.map((n) => n.id));
      edges = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    }
    if (f.orphans_only) {
      const linked = new Set(edges.flatMap((e) => [e.source, e.target]));
      nodes = nodes.filter((n) => !linked.has(n.id));
      edges = [];
    }
    return { ...g, root: q.root, nodes, edges, counts: { nodes: nodes.length, edges: edges.length } };
  }

  async node(id: string) {
    const d = this.bundle.details[id];
    if (!d) throw new ApiError("no details for this node in the export", {});
    return d;
  }

  async search(q: string, level: string) {
    const needle = q.toLowerCase().trim();
    if (!needle) return [];
    const g = this.base(level, "import");
    return g.nodes
      .map((n) => {
        const hay = `${n.id} ${n.label} ${n.doc ?? ""}`.toLowerCase();
        const score = n.label.toLowerCase() === needle ? 3 : n.label.toLowerCase().includes(needle) ? 2 : hay.includes(needle) ? 1 : 0;
        return { n, score };
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score || b.n.rank - a.n.rank)
      .slice(0, 15)
      .map(({ n }) => ({ id: n.id, kind: n.kind, file: n.file, snippet: n.doc || n.signature || "", node: n.id }));
  }

  async path(from: string, to: string, layer: string, level: string) {
    const g = this.base(level, layer);
    for (const directed of [true, false]) {
      const adj = new Map<string, string[]>();
      for (const e of g.edges) {
        (adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target);
        if (!directed) (adj.get(e.target) ?? adj.set(e.target, []).get(e.target)!).push(e.source);
      }
      const prev = new Map<string, string | null>([[from, null]]);
      const queue = [from];
      while (queue.length) {
        const cur = queue.shift()!;
        if (cur === to) break;
        for (const n of adj.get(cur) ?? []) if (!prev.has(n)) (prev.set(n, cur), queue.push(n));
      }
      if (prev.has(to)) {
        const path = [to];
        while (prev.get(path[path.length - 1])) path.push(prev.get(path[path.length - 1])!);
        return { nodes: path.reverse(), directed };
      }
    }
    return { nodes: [], directed: true };
  }

  async impact(id: string, level: string) {
    const g = this.base(level, level === "symbol" ? "call" : "import");
    const reversed = g.edges.map((e) => ({ ...e, source: e.target, target: e.source }));
    const rings = neighbourhood(reversed, id, 3, true);
    rings.delete(id);
    return { rings: Object.fromEntries(rings), tests: [], totals: { symbols: rings.size, files: rings.size } };
  }

  async diff(): Promise<{ files: Record<string, string>; changed_ids: string[] }> {
    throw new ApiError("diff mode needs `prism view` (git is not available in an export)", {});
  }

  async layout() {
    try {
      return JSON.parse(localStorage.getItem("prism-layout") ?? "{}");
    } catch {
      return {};
    }
  }
  async saveLayout(positions: Record<string, [number, number]>) {
    try {
      localStorage.setItem("prism-layout", JSON.stringify(positions));
    } catch {
      /* storage may be unavailable */
    }
  }
  async views() {
    try {
      return JSON.parse(localStorage.getItem("prism-views") ?? "{}");
    } catch {
      return {};
    }
  }
  async saveView(name: string, state: unknown) {
    const views = await this.views();
    views[name] = state;
    try {
      localStorage.setItem("prism-views", JSON.stringify(views));
    } catch {
      /* ignore */
    }
  }
  subscribe(_i: (e: IndexEvent) => void, _a: (e: ActivityEvent) => void, onStatus: (ok: boolean) => void) {
    onStatus(false);
  }
}

export function createSource(): DataSource {
  return window.__PRISM_STATIC__ ? new StaticSource(window.__PRISM_STATIC__) : new HttpSource();
}
