// Saved views come from storage (server cache or localStorage): validate before use.
import type { ColorBy, SizeBy } from "./encode";
import type { Filters, Layer, Level } from "./types";

// Local lists (type-checked against the unions) keep this module free of runtime imports.
const COLOR_VALUES: readonly ColorBy[] = ["group", "community", "risk", "findings", "owner", "recency", "kind", "language"];
const SIZE_VALUES: readonly SizeBy[] = ["rank", "loc", "fan_in", "blast"];

export const LEVEL_VALUES: readonly Level[] = ["package", "file", "symbol"];
export const LAYER_VALUES: readonly Layer[] = ["import", "call", "tests", "cochange", "routes"];
export const FILTER_KINDS = ["cluster", "module", "class", "function", "method", "test", "route"];

export interface SavedView {
  level: Level;
  layer: Layer;
  root: string | null;
  depth: number;
  filters: Filters;
  colorBy: ColorBy;
  sizeBy: SizeBy;
  drill: string | null;
  camera?: { x: number; y: number; ratio: number; angle: number };
}

function isNum(v: unknown, min = -Infinity, max = Infinity): v is number {
  return typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;
}

export function parseView(raw: unknown): SavedView | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Record<string, unknown>;
  if (!LEVEL_VALUES.includes(v.level as Level) || !LAYER_VALUES.includes(v.layer as Layer)) return null;
  if (!COLOR_VALUES.includes(v.colorBy as ColorBy) || !SIZE_VALUES.includes(v.sizeBy as SizeBy)) return null;
  const f = (v.filters && typeof v.filters === "object" ? v.filters : {}) as Record<string, unknown>;
  const filters: Filters = {
    path: typeof f.path === "string" ? f.path.slice(0, 300) : "",
    kinds: Array.isArray(f.kinds) ? f.kinds.filter((k): k is string => typeof k === "string" && FILTER_KINDS.includes(k)) : [],
    hide_tests: f.hide_tests === true,
    orphans_only: f.orphans_only === true,
    min_rank: isNum(f.min_rank, 0, 1) ? f.min_rank : 0,
    min_risk: isNum(f.min_risk, 0, 1) ? f.min_risk : 0,
    changed_since: typeof f.changed_since === "string" ? f.changed_since.slice(0, 200) : "",
  };
  const cam = v.camera as Record<string, unknown> | undefined;
  const camera = cam && isNum(cam.x) && isNum(cam.y) && isNum(cam.ratio, 0.001, 100) && isNum(cam.angle)
    ? { x: cam.x, y: cam.y, ratio: cam.ratio, angle: cam.angle } : undefined;
  return {
    level: v.level as Level,
    layer: v.layer as Layer,
    root: typeof v.root === "string" && v.root.length < 500 ? v.root : null,
    depth: isNum(v.depth, 1, 4) ? Math.round(v.depth) : 2,
    filters,
    colorBy: v.colorBy as ColorBy,
    sizeBy: v.sizeBy as SizeBy,
    drill: typeof v.drill === "string" ? v.drill : null,
    camera,
  };
}
