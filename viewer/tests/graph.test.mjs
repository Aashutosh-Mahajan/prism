import test from "node:test";
import assert from "node:assert/strict";
import {
  adjacency, edgeKey, nearestInDirection, pathEdges, percentile, relations, RequestGeneration, seedPositions,
} from "../.test-build/graph-utils.js";
import { buildContext, categoricalScale, legend, nodeColor, nodeType, NEUTRAL, setTheme } from "../.test-build/encode.js";
import { parseView } from "../.test-build/views.js";

test("adjacency includes both endpoints and deduplicates repeated relationships", () => {
  const graph = adjacency([{ source: "a", target: "b" }, { source: "a", target: "b" }, { source: "c", target: "a" }]);
  assert.deepEqual([...graph.get("a")], ["b", "c"]);
  assert.deepEqual([...graph.get("b")], ["a"]);
});

test("relations keep direction for the inspector", () => {
  const r = relations([{ source: "a", target: "b" }, { source: "c", target: "b" }]);
  assert.deepEqual(r.incoming.get("b"), ["a", "c"]);
  assert.deepEqual(r.outgoing.get("a"), ["b"]);
  assert.equal(r.incoming.get("a"), undefined);
});

test("path highlights exclude chords and reverse edges unless direction is ignored", () => {
  const edges = pathEdges(["a", "b", "c"], true);
  assert.ok(edges.has(edgeKey("a", "b")));
  assert.ok(!edges.has(edgeKey("a", "c")));
  assert.ok(!edges.has(edgeKey("b", "a")));
  assert.ok(pathEdges(["a", "b"], false).has(edgeKey("b", "a")));
});

test("new input invalidates an older response even before the next request starts", () => {
  const requests = new RequestGeneration();
  const first = requests.next();
  const next = requests.next();
  assert.equal(requests.current(first), false);
  assert.equal(requests.current(next), true);
});

test("seeded layout is deterministic and keeps groups apart", () => {
  const nodes = [];
  for (const g of ["a", "b", "c"]) for (let i = 0; i < 30; i++) nodes.push({ id: `${g}${i}`, group: g, rank: i });
  const one = seedPositions(nodes);
  const two = seedPositions([...nodes].reverse());
  assert.deepEqual([...one.entries()].sort(), [...two.entries()].sort());
  const centre = (g) => {
    const pts = nodes.filter((n) => n.group === g).map((n) => one.get(n.id));
    return { x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length };
  };
  const spread = (g) => {
    const c = centre(g);
    return Math.max(...nodes.filter((n) => n.group === g).map((n) => Math.hypot(one.get(n.id).x - c.x, one.get(n.id).y - c.y)));
  };
  const [a, b] = [centre("a"), centre("b")];
  assert.ok(Math.hypot(a.x - b.x, a.y - b.y) > spread("a"), "group centres are further apart than a group's own radius");
  for (const p of one.values()) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

test("arrow-key navigation picks the nearest node along the direction", () => {
  const points = [["right", { x: 10, y: 0 }], ["far-right", { x: 50, y: 0 }], ["up", { x: 0, y: -10 }], ["diag", { x: 10, y: 9 }]];
  const from = { x: 0, y: 0 };
  assert.equal(nearestInDirection(from, points, "right"), "right");
  assert.equal(nearestInDirection(from, points, "up"), "up");
  assert.equal(nearestInDirection(from, points, "left"), null);
  assert.equal(nearestInDirection(from, points, "down"), "diag");
});

test("percentile ranks", () => {
  assert.equal(percentile([1, 2, 3, 4], 4), 75);
  assert.equal(percentile([1, 2, 3, 4], 1), 0);
  assert.equal(percentile([], 3), 0);
});

test("the twelve largest groups get twelve distinct colours", () => {
  setTheme("dark");
  const keys = Array.from({ length: 12 }, (_, i) => `group${i}`);
  const scale = categoricalScale(keys);
  assert.equal(new Set(scale.values()).size, 12);
  const darkColour = categoricalScale(["only"]).get("only");
  setTheme("light");
  assert.notEqual(categoricalScale(["only"]).get("only"), darkColour, "light theme uses its own, deeper palette");
  setTheme("dark");
});

test("zero-findings legend agrees with actual node encoding", () => {
  const node = { id: "n", group: "g", findings: 0, loc: 1, rank: 1, blast: 0, risk: 0, language: "python", kind: "module" };
  const ctx = buildContext([node], new Map());
  assert.equal(nodeColor(node, "findings", ctx), NEUTRAL);
  assert.equal(legend("findings", [node], ctx)[0].color, NEUTRAL);
});

test("legend summarises a long tail instead of dropping it silently", () => {
  const nodes = Array.from({ length: 15 }, (_, i) => ({ id: `n${i}`, group: `g${i}`, rank: 1, loc: 1, blast: 0, risk: 0, language: "python", kind: "module" }));
  const items = legend("group", nodes, buildContext(nodes, new Map()));
  assert.equal(items.length, 10);
  assert.match(items.at(-1).label, /^6 more/);
});

test("shapes encode node kinds", () => {
  assert.equal(nodeType({ kind: "module" }), "square");
  assert.equal(nodeType({ kind: "cluster" }), "border");
  assert.equal(nodeType({ kind: "function" }), "circle");
});

test("saved views are validated before use", () => {
  const good = parseView({
    level: "file", layer: "call", root: "a.b", depth: 3, colorBy: "risk", sizeBy: "loc", drill: null,
    filters: { path: "src/*", kinds: ["module", "bogus"], min_rank: 0.5, min_risk: 7 },
    camera: { x: 1, y: 2, ratio: 0.5, angle: 0 },
  });
  assert.equal(good.level, "file");
  assert.deepEqual(good.filters.kinds, ["module"]);
  assert.equal(good.filters.min_risk, 0);
  assert.deepEqual(good.camera, { x: 1, y: 2, ratio: 0.5, angle: 0 });
  assert.equal(parseView({ ...good, level: "galaxy" }), null);
  assert.equal(parseView({ ...good, colorBy: "toString" }), null);
  assert.equal(parseView(null), null);
  const noCamera = parseView({ ...good, camera: { x: Infinity, y: 0, ratio: 1, angle: 0 } });
  assert.equal(noCamera.camera, undefined);
});
