import test from "node:test";
import assert from "node:assert/strict";
import { StaticSource } from "../.test-build/data.js";

const node = (id, kind, group, file = null) => ({id, label:id, kind, group, file, rank:1, risk:0, loc:1, blast:0, test:false});
const graph = (level, nodes, edges = []) => ({level, layer:"import", nodes, edges, root:null, truncated:0, counts:{nodes:nodes.length,edges:edges.length}});
const filters = {path:"",kinds:[],hide_tests:false,orphans_only:false,min_rank:0,min_risk:0,changed_since:""};
const source = new StaticSource({meta:{}, details:{}, graphs:{
  "package|import": graph("package", [node("pkg:a","cluster","a"),node("pkg:b","cluster","b")]),
  "file|import": graph("file", [node("src/a.py","module","a","src/a.py"),node("src/b.py","module","b","src/b.py")], [{source:"src/a.py",target:"src/b.py"}]),
}});

test("package glob filters match member files", async () => {
  const result = await source.graph({level:"package",layer:"import",root:null,depth:2,filters:{...filters,path:"src/a*"}});
  assert.deepEqual(result.nodes.map(n => n.id), ["pkg:a"]);
});
test("missing layers and roots produce explicit errors", async () => {
  await assert.rejects(source.graph({level:"file",layer:"call",root:null,depth:2,filters}), /no file-level call/);
  await assert.rejects(source.graph({level:"file",layer:"import",root:"missing",depth:2,filters}), /not in this graph/);
});
test("filtered fan-in reflects the visible relations", async () => {
  const result = await source.graph({level:"file",layer:"import",root:null,depth:2,filters:{...filters,path:"src/b.py"}});
  assert.equal(result.nodes[0].fan_in, 0);
  const full = await source.graph({level:"file",layer:"import",root:null,depth:2,filters});
  assert.equal(full.nodes.find(n => n.id === "src/b.py").fan_in, 1);
});
