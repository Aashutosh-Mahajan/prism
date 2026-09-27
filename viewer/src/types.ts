export type Level = "package" | "file" | "symbol";
export type Layer = "import" | "call" | "tests" | "cochange" | "routes";

export interface GNode {
  id: string;
  label: string;
  kind: string;
  file: string | null;
  module?: string;
  group: string;
  dir?: string;
  lines?: [number, number];
  rank: number;
  loc: number;
  blast: number;
  risk: number;
  owner: string | null;
  language: string;
  last_changed: number | null;
  findings: number;
  test: boolean;
  dead?: boolean;
  signature?: string;
  doc?: string;
  fan_in?: number;
  fan_out?: number;
  distance?: number;
  change?: string;
  files?: number;
  community?: number; // computed by PRISM (Louvain over imports + calls); -1 for tests
}

export interface GEdge {
  id: string;
  source: string;
  target: string;
  layer: string;
  weight: number;
  confidence: string;
  cycle?: boolean;
}

export interface GraphPayload {
  level: Level;
  layer: Layer;
  root: string | null;
  nodes: GNode[];
  edges: GEdge[];
  truncated: number;
  counts: { nodes: number; edges: number };
}

export interface Filters {
  path: string;
  kinds: string[];
  hide_tests: boolean;
  orphans_only: boolean;
  min_rank: number;
  min_risk: number;
  changed_since: string;
}

export interface GraphQuery {
  level: Level;
  layer: Layer;
  root: string | null;
  depth: number;
  filters: Filters;
}

export interface SearchHit {
  id: string;
  kind: string;
  file?: string | null;
  snippet?: string;
  node?: string | null;
}

export interface ImpactResult {
  rings: Record<string, number>;
  tests: string[];
  totals: { symbols: number; files: number };
}

export interface PathResult {
  nodes: string[];
  directed: boolean;
}

export interface Meta {
  project: string;
  stats: Record<string, unknown>;
  last_scan: string | null;
  git: boolean;
  has_routes: boolean;
  static: boolean;
}

export type Details = Record<string, any>;

export interface IndexEvent {
  added: string[];
  removed: string[];
  changed: string[];
}

export interface ActivityEvent {
  t: number;
  op: string;
  ids: string[];
}
