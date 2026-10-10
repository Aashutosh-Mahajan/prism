import test from "node:test";
import assert from "node:assert/strict";
import { bandLabel, layeredPositions } from "../.test-build/layered.js";
import { collapsed } from "../.test-build/graph-utils.js";

const node = (id, tier, extra = {}) => ({ id, tier, size: 6, area: "a", rank: 1, label: id.length, ...extra });

test("layers put foundations at the bottom and dependents above them", () => {
  const nodes = [node("app", 2), node("svc", 1), node("db", 0), node("lonely", 0)];
  const edges = [{ source: "app", target: "svc" }, { source: "svc", target: "db" }];
  const { positions, bands } = layeredPositions(nodes, edges, { width: 1000, height: 700 });
  assert.ok(positions.get("app").y > positions.get("svc").y, "y grows upward: entry points on top");
  assert.ok(positions.get("svc").y > positions.get("db").y);
  // Unconnected nodes get their own row under the foundations.
  assert.ok(positions.get("lonely").y < positions.get("db").y);
  assert.deepEqual(bands.map((b) => b.tier), [-1, 0, 1, 2]);
  assert.equal(bandLabel(-1, 3), "Unconnected");
  assert.equal(bandLabel(0, 3), "Foundations");
  assert.equal(bandLabel(2, 3), "Entry points");
  assert.equal(bandLabel(1, 3), "Tier 1");
});

test("layers order a row by its neighbours and keep labels apart", () => {
  const nodes = [node("top-l", 1), node("top-r", 1), node("b-r", 0), node("b-l", 0)];
  const edges = [{ source: "top-l", target: "b-l" }, { source: "top-r", target: "b-r" }];
  const { positions } = layeredPositions(nodes, edges, { width: 1000, height: 700 });
  const left = (id) => positions.get(id).x;
  // Each top node sits on the same side as what it depends on: no crossing.
  assert.equal(left("top-l") < left("top-r"), left("b-l") < left("b-r"));
  assert.ok(Math.abs(left("b-l") - left("b-r")) > 6 * 2 + 3 * 6.8, "slots leave room for the label");
});

test("large layers keep roughly the viewport's shape instead of a tall column", () => {
  const nodes = [];
  const edges = [];
  for (let t = 0; t < 20; t++) {
    for (let i = 0; i < 60; i++) {
      nodes.push(node(`n${t}-${i}`, t, { label: 0 }));
      if (t > 0) edges.push({ source: `n${t}-${i}`, target: `n${t - 1}-${i}` });
    }
  }
  const { positions } = layeredPositions(nodes, edges, { width: 1200, height: 800 });
  const xs = [...positions.values()].map((p) => p.x);
  const ys = [...positions.values()].map((p) => p.y);
  const ratio = (Math.max(...ys) - Math.min(...ys)) / (Math.max(...xs) - Math.min(...xs));
  assert.ok(ratio > 0.25 && ratio < 2.5, `height/width ${ratio.toFixed(2)} stays near the viewport's`);
});

test("layered positions are deterministic", () => {
  const nodes = [node("a", 1), node("b", 0), node("c", 0)];
  const edges = [{ source: "a", target: "b" }, { source: "a", target: "c" }];
  const one = layeredPositions(nodes, edges);
  const two = layeredPositions(nodes, edges);
  assert.deepEqual([...one.positions], [...two.positions]);
});

test("a layout that never unfolded is recognised and not trusted", () => {
  assert.equal(collapsed([[5, 5], [5, 5], [5, 5]]), true);
  assert.equal(collapsed([[0, 0], [1, 0], [0, 1]]), false);
  assert.equal(collapsed([[0, 0], [NaN, 1], [2, 2]]), true);
  assert.equal(collapsed([[1, 1], [1, 1]]), false, "two points are too few to judge");
});
