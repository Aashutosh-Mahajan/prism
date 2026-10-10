// Live force layout, as in Obsidian's graph view: a d3-force simulation with Obsidian's four
// forces (centre, repel, link force, link distance) that keeps moving while it settles, lets a
// dragged node pull its neighbours along, and comes to rest on its own. Unconnected nodes end
// up orbiting the connected cloud, which gives the familiar round graph. Settled positions are
// saved so reopening is instant.
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

import type { App } from "./app";
import { collapsed } from "./graph-utils";
import { $, store, stored } from "./ui";

interface SimNode extends SimulationNodeDatum {
  id: string;
  r: number;
}

/** Obsidian's force sliders (same names, same meaning). */
export interface Forces {
  center: number; // 0..1
  repel: number; // 0..20
  linkForce: number; // 0..1
  linkDistance: number; // 30..500
}

export const DEFAULT_FORCES: Forces = { center: 0.5, repel: 10, linkForce: 1, linkDistance: 120 };
const FORCE_INPUTS: Record<keyof Forces, string> = {
  center: "ph-gravity", repel: "ph-scaling", linkForce: "ph-weight", linkDistance: "ph-slow",
};

export function loadForces(): Forces {
  try {
    const raw = JSON.parse(stored("prism-forces") ?? "{}") as Partial<Forces>;
    const out = { ...DEFAULT_FORCES };
    for (const key of Object.keys(DEFAULT_FORCES) as (keyof Forces)[]) {
      const v = raw[key];
      if (typeof v === "number" && Number.isFinite(v)) out[key] = v;
    }
    return out;
  } catch {
    return { ...DEFAULT_FORCES };
  }
}

export class LayoutController {
  private sim: Simulation<SimNode, SimulationLinkDatum<SimNode>> | null = null;
  private byId = new Map<string, SimNode>();
  private saveTimer: number | undefined;
  forces: Forces = loadForces();
  /** When true, the layout never starts on its own (the user stopped it). */
  frozen = false;

  constructor(private readonly app: App) {
    for (const [key, id] of Object.entries(FORCE_INPUTS) as [keyof Forces, string][]) {
      const input = document.getElementById(id) as HTMLInputElement | null;
      if (input) input.value = String(this.forces[key]);
      const out = document.getElementById(`${id}-out`);
      if (out) out.textContent = String(this.forces[key]);
    }
  }

  get running(): boolean {
    return this.sim !== null;
  }

  /** Start settling: from scratch for a new view, gently when only a few nodes are new. */
  run(fromScratch: boolean, _durationMs?: number): void {
    if (this.frozen) return;
    this.start(fromScratch ? 1 : 0.35);
  }

  start(alpha = 0.6): void {
    this.stop();
    const g = this.app.graph;
    if (g.order < 2) return;
    this.app.motion.cancel();
    if (this.app.state.layoutMode !== "organic") this.app.setLayoutMode("organic", false);
    const nodes: SimNode[] = g.mapNodes((id, a) => ({
      id,
      x: a.x as number,
      y: a.y as number,
      r: (a.size as number) ?? 5,
      ...(a.fixed ? { fx: a.x as number, fy: a.y as number } : {}),
    }));
    this.byId = new Map(nodes.map((n) => [n.id, n]));
    const degree = new Map<string, number>();
    const links = g.mapEdges((_e, a, source, target) => {
      degree.set(source, (degree.get(source) ?? 0) + 1);
      degree.set(target, (degree.get(target) ?? 0) + 1);
      return { source, target, weight: (a.weight as number) ?? 1 };
    });
    const f = this.forces;
    const n = nodes.length;
    this.sim = forceSimulation<SimNode>(nodes)
      .force(
        "link",
        forceLink<SimNode, SimulationLinkDatum<SimNode>>(links)
          .id((d) => d.id)
          .distance(f.linkDistance * 0.5)
          // d3's default (weaker links for busier nodes), scaled by the link-force slider.
          .strength((l) => {
            const s = typeof l.source === "object" ? l.source.id : String(l.source);
            const t = typeof l.target === "object" ? l.target.id : String(l.target);
            return f.linkForce / Math.max(1, Math.min(degree.get(s) ?? 1, degree.get(t) ?? 1));
          }),
      )
      .force("charge", forceManyBody<SimNode>().strength(-f.repel * 25).theta(n > 1000 ? 1.1 : 0.9).distanceMax(f.linkDistance * 8))
      .force("x", forceX<SimNode>(0).strength(f.center * 0.1))
      .force("y", forceY<SimNode>(0).strength(f.center * 0.1))
      .force("collide", forceCollide<SimNode>((d) => d.r + 3).iterations(1))
      .velocityDecay(0.42)
      .alphaDecay(n > 1500 ? 0.04 : 0.025)
      .alpha(alpha)
      .on("tick", () => this.write())
      .on("end", () => {
        this.sim = null;
        this.status(false);
        this.save();
      });
    this.status(true);
  }

  private write(): void {
    const ids = this.byId;
    this.app.graph.updateEachNodeAttributes((id, a) => {
      const n = ids.get(id);
      return n && n.x !== undefined && n.y !== undefined ? { ...a, x: n.x, y: n.y } : a;
    }, { attributes: ["x", "y"] });
    this.app.refresh();
  }

  private status(on: boolean): void {
    $<HTMLInputElement>("ph-run").checked = on;
    $("layout-state").textContent = on ? "Arranging…" : "";
    if (on) $("spectrum").classList.add("busy");
    else if ($("loading").hidden) $("spectrum").classList.remove("busy");
  }

  stop(save = false): void {
    if (this.sim) {
      this.sim.stop();
      this.sim = null;
    }
    this.status(false);
    if (save) this.save();
  }

  // --- dragging: the node follows the pointer and the graph reacts around it -------------

  grab(id: string): void {
    if (this.app.state.layoutMode !== "organic") return;
    if (!this.sim) {
      if (this.frozen) return;
      this.start(0.12);
    }
    const n = this.byId.get(id);
    if (!n || !this.sim) return;
    n.fx = n.x;
    n.fy = n.y;
    this.sim.alphaTarget(0.25).restart();
  }

  drag(id: string, x: number, y: number): void {
    const n = this.byId.get(id);
    if (n && this.sim) {
      n.fx = x;
      n.fy = y;
    }
  }

  release(id: string): void {
    const n = this.byId.get(id);
    const pinned = Boolean(this.app.graph.hasNode(id) && this.app.graph.getNodeAttribute(id, "fixed"));
    if (n && !pinned) {
      n.fx = null;
      n.fy = null;
    }
    this.sim?.alphaTarget(0);
  }

  /** Apply the current force sliders (restarting gently if already running). */
  retune(): void {
    for (const [key, id] of Object.entries(FORCE_INPUTS) as [keyof Forces, string][]) {
      const v = Number(($(id) as HTMLInputElement).value);
      if (Number.isFinite(v)) this.forces[key] = v;
    }
    store("prism-forces", JSON.stringify(this.forces));
    if (!this.frozen) this.start(0.5);
  }

  /** Obsidian's "Animate": scatter and let the whole graph settle again. */
  rearrange(): void {
    const r = Math.sqrt(this.app.graph.order + 10) * 6;
    this.app.graph.forEachNode((id) =>
      this.app.graph.mergeNodeAttributes(id, { x: (Math.random() - 0.5) * r, y: (Math.random() - 0.5) * r, fixed: undefined }),
    );
    this.app.savedPositions = {};
    this.frozen = false;
    this.start(1);
  }

  unpinAll(): void {
    this.app.graph.forEachNode((id) => this.app.graph.removeNodeAttribute(id, "fixed"));
    for (const n of this.byId.values()) {
      n.fx = null;
      n.fy = null;
    }
  }

  save(): void {
    // The layered arrangement is derived; only the organic one is worth keeping.
    if (this.app.state.layoutMode !== "organic") return;
    window.clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => {
      // Mid-animation positions are not an arrangement anyone chose.
      if (this.app.motion.running || collapsed(this.app.graph.mapNodes((_, a) => [a.x as number, a.y as number]))) return;
      const positions: Record<string, [number, number]> = {};
      this.app.graph.forEachNode((id, a) => {
        const pos: [number, number] = [Math.round((a.x as number) * 100) / 100, Math.round((a.y as number) * 100) / 100];
        if (Number.isFinite(pos[0]) && Number.isFinite(pos[1])) {
          positions[id] = pos;
          this.app.savedPositions[id] = pos;
        }
      });
      this.app.source.saveLayout(positions).catch(() => undefined);
    }, 400);
  }
}
