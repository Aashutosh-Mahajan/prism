import test from "node:test";
import assert from "node:assert/strict";
import { adjacency, pathEdges, RequestGeneration } from "../.test-build/graph-utils.js";
import { buildContext, legend, nodeColor, NEUTRAL } from "../.test-build/encode.js";

test("adjacency includes both endpoints and deduplicates repeated relationships", () => {
  const graph = adjacency([{source:"a",target:"b"},{source:"a",target:"b"},{source:"c",target:"a"}]);
  assert.deepEqual([...graph.get("a")], ["b", "c"]);
  assert.deepEqual([...graph.get("b")], ["a"]);
});

test("path highlights exclude chords and reverse edges unless direction is ignored", () => {
  const edges = pathEdges(["a", "b", "c"], true);
  assert.ok(edges.has(JSON.stringify(["a", "b"])));
  assert.ok(!edges.has(JSON.stringify(["a", "c"])));
  assert.ok(!edges.has(JSON.stringify(["b", "a"])));
  assert.ok(pathEdges(["a", "b"], false).has(JSON.stringify(["b", "a"])));
});

test("new input invalidates an older response even before the next request starts", () => {
  const requests = new RequestGeneration();
  const first = requests.next();
  const next = requests.next();
  assert.equal(requests.current(first), false);
  assert.equal(requests.current(next), true);
});

test("zero-findings legend agrees with actual node encoding", () => {
  const node = { findings: 0, loc: 1, rank: 1, blast: 0 };
  const ctx = buildContext([node], new Map());
  assert.equal(nodeColor(node, "findings", ctx), NEUTRAL);
  assert.equal(legend("findings", [node], ctx)[0].color, NEUTRAL);
});
