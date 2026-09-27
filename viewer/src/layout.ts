// Force layout in a Web Worker (ForceAtlas2), started from seeded cluster positions so it
// converges quickly, stopped automatically, and persisted so reopening is instant.
import FA2Layout from "graphology-layout-forceatlas2/worker";

import type { App } from "./app";
import { $ } from "./ui";

function value(id: string): number {
  return Number($<HTMLInputElement>(id).value);
}

function checked(id: string): boolean {
  return $<HTMLInputElement>(id).checked;
}

export class LayoutController {
  private worker: FA2Layout | null = null;
  private timer: number | undefined;
  private saveTimer: number | undefined;
  /** When true, the layout never starts on its own (the user pinned the arrangement). */
  frozen = false;

  constructor(private readonly app: App) {}

  get running(): boolean {
    return this.worker !== null;
  }

  private settings() {
    const n = this.app.graph.order;
    return {
      gravity: value("ph-gravity"),
      scalingRatio: value("ph-scaling"),
      slowDown: value("ph-slow") * (n > 2000 ? 2 : 1),
      edgeWeightInfluence: value("ph-weight"),
      linLogMode: checked("ph-linlog"),
      strongGravityMode: checked("ph-strong"),
      barnesHutOptimize: n > 300,
      barnesHutTheta: n > 3000 ? 0.9 : 0.6,
      adjustSizes: false,
    };
  }

  /** Run for a bounded time that grows gently with graph size; fit the camera when done. */
  run(fromScratch: boolean, durationMs?: number): void {
    if (this.frozen && durationMs === undefined) return;
    const n = this.app.graph.order;
    const budget = durationMs ?? (fromScratch ? Math.min(6000, 1600 + n * 1.2) : Math.min(2500, 800 + n * 0.4));
    this.start(budget);
  }

  start(durationMs?: number): void {
    this.stop();
    if (this.app.graph.order < 2) return;
    this.worker = new FA2Layout(this.app.graph, { settings: this.settings(), getEdgeWeight: "weight" });
    this.worker.start();
    $<HTMLInputElement>("ph-run").checked = true;
    $("layout-state").textContent = "Arranging…";
    $("spectrum").classList.add("busy");
    if (durationMs) {
      this.timer = window.setTimeout(() => {
        this.stop(true);
        this.app.fit();
      }, durationMs);
    }
  }

  stop(save = false): void {
    window.clearTimeout(this.timer);
    if (this.worker) {
      this.worker.kill();
      this.worker = null;
    }
    $<HTMLInputElement>("ph-run").checked = false;
    $("layout-state").textContent = "";
    if ($("loading").hidden) $("spectrum").classList.remove("busy");
    if (save) this.save();
  }

  /** Restart with the current slider values (only if it was already running). */
  retune(): void {
    if (this.worker) this.start();
  }

  rearrange(): void {
    const r = Math.sqrt(this.app.graph.order + 10) * 8;
    this.app.graph.forEachNode((id) =>
      this.app.graph.mergeNodeAttributes(id, { x: (Math.random() - 0.5) * r, y: (Math.random() - 0.5) * r, fixed: undefined }),
    );
    this.app.savedPositions = {};
    this.start(Math.min(8000, 2500 + this.app.graph.order * 2));
  }

  unpinAll(): void {
    this.app.graph.forEachNode((id) => this.app.graph.removeNodeAttribute(id, "fixed"));
  }

  save(): void {
    window.clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => {
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
