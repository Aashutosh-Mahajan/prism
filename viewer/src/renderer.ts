// Sigma (WebGL) renderer: node/edge programs, labels, and the reducers that turn view state
// (hover, selection, keyboard focus, overlays, live activity) into what is drawn.
import { createNodeBorderProgram } from "@sigma/node-border";
import { NodeSquareProgram } from "@sigma/node-square";
import Sigma from "sigma";
import { EdgeArrowProgram } from "sigma/rendering";

import type { App } from "./app";
import { edgeKey } from "./graph-utils";
import { palette } from "./theme";

export const TRAIL_MS = 20_000;
const TRAIL_HOT_MS = 4_000;
const PULSE_MS = 2_400;
const LABEL_FONT = '"Prism Mono", "JetBrains Mono", Consolas, monospace';

type Ctx = CanvasRenderingContext2D;
interface Drawn { x: number; y: number; size: number; label?: string | null; color: string; focusRing?: boolean }

function drawLabel(ctx: Ctx, d: Drawn, weight = 400): void {
  if (!d.label) return;
  ctx.font = `${weight} 11px ${LABEL_FONT}`;
  ctx.lineWidth = 3.5;
  ctx.lineJoin = "round";
  ctx.strokeStyle = palette.canvas;
  ctx.fillStyle = palette.label;
  const x = d.x + d.size + 6;
  ctx.strokeText(d.label, x, d.y + 4);
  ctx.fillText(d.label, x, d.y + 4);
}

function drawHighlight(ctx: Ctx, d: Drawn): void {
  // Ring around the node; a second, accent ring marks keyboard focus.
  ctx.beginPath();
  ctx.arc(d.x, d.y, d.size + 4, 0, Math.PI * 2);
  ctx.strokeStyle = d.color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
  if (d.focusRing) {
    ctx.beginPath();
    ctx.arc(d.x, d.y, d.size + 8, 0, Math.PI * 2);
    ctx.strokeStyle = palette.accent;
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 3]);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (!d.label) return;
  ctx.font = `600 12px ${LABEL_FONT}`;
  const w = ctx.measureText(d.label).width;
  const x = d.x + d.size + 10;
  ctx.fillStyle = palette.chrome;
  ctx.strokeStyle = palette.rule;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(x - 7, d.y - 12, w + 14, 24, 6);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = palette.label;
  ctx.fillText(d.label, x, d.y + 4);
}

export function createRenderer(app: App, container: HTMLElement): Sigma {
  const s = app.state;
  const renderer = new Sigma(app.graph, container, {
    nodeProgramClasses: {
      square: NodeSquareProgram,
      border: createNodeBorderProgram({
        borders: [
          { size: { value: 0.3 }, color: { attribute: "color" } },
          { size: { fill: true }, color: { attribute: "innerColor" } },
        ],
      }),
    },
    edgeProgramClasses: { arrow: EdgeArrowProgram },
    defaultEdgeType: "arrow",
    renderEdgeLabels: false,
    labelRenderedSizeThreshold: 7,
    labelDensity: 0.7,
    labelGridCellSize: 120,
    labelFont: LABEL_FONT,
    labelSize: 11,
    defaultDrawNodeLabel: (ctx, data) => drawLabel(ctx, data as Drawn),
    defaultDrawNodeHover: (ctx, data) => drawHighlight(ctx, data as Drawn),
    zIndex: true,
    allowInvalidContainer: true,
    minCameraRatio: 0.02,
    maxCameraRatio: 25,
    nodeReducer: (node, data) => {
      const res: Record<string, unknown> = { ...data };
      const now = performance.now();
      let faded = false;
      if (s.hovered && node !== s.hovered && !app.neighbors.get(s.hovered)?.has(node)) faded = true;
      if (s.rings) {
        const d = s.rings.get(node);
        if (d !== undefined) res.color = palette.rings[Math.min(4, d)] || res.color;
        else if (node !== s.selected) faded = true;
      }
      if (s.path) {
        if (s.path.has(node)) res.highlighted = true;
        else faded = true;
      }
      if (s.diff) {
        const status = s.diff.get(node);
        if (status) res.color = palette.diff[status] ?? res.color;
        else faded = true;
      }
      if (s.showDead && data.dead) res.color = palette.danger;
      if (s.showActivity) {
        const t = s.trail.get(node);
        if (t !== undefined && now - t < TRAIL_MS) {
          res.highlighted = true;
          res.zIndex = 2;
          if (now - t < TRAIL_HOT_MS) res.color = palette.accent;
        }
      }
      const p = s.pulses.get(node);
      if (p !== undefined && now - p < PULSE_MS) {
        if (!app.reducedMotion.matches) {
          const k = 1 - (now - p) / PULSE_MS;
          res.size = (data.size as number) * (1 + 0.8 * k * Math.abs(Math.sin((now - p) / 150)));
        }
        res.highlighted = true;
      }
      if (node === s.selected || node === s.focused) {
        res.highlighted = true;
        res.zIndex = 3;
        res.focusRing = node === s.focused;
        faded = false;
      }
      if (faded) {
        res.color = palette.faded;
        res.innerColor = palette.faded;
        res.label = "";
        res.zIndex = 0;
      }
      if (!s.showLabels && !res.highlighted) res.label = "";
      return res;
    },
    edgeReducer: (edge, data) => {
      const res: Record<string, unknown> = { ...data };
      const [source, target] = app.graph.extremities(edge);
      res.color = data.confidence === "low" ? palette.edgeWeak : palette.edge;
      if (s.showCycles && data.cycle) res.color = palette.danger;
      const focus = s.hovered ?? (s.selected && !s.rings && !s.path && !s.diff ? s.selected : null);
      if (focus) {
        if (source !== focus && target !== focus) {
          if (s.hovered) res.hidden = true;
        } else {
          res.color = palette.accent;
          res.size = Math.max(1.4, (data.size as number) ?? 1);
          res.zIndex = 1;
        }
      }
      if (s.path) {
        if (s.pathEdges.has(edgeKey(source, target))) {
          res.color = palette.accent;
          res.size = 2.5;
        } else res.hidden = true;
      }
      if (s.rings && !(s.rings.has(source) || source === s.selected) && !(s.rings.has(target) || target === s.selected)) {
        res.hidden = true;
      }
      if (s.diff && !s.diff.has(source) && !s.diff.has(target)) res.hidden = true;
      return res;
    },
  });
  bindDragging(app, renderer);
  return renderer;
}

/** Whether the pointer gesture that just ended moved a node (so it wasn't a click). */
export const drag = { moved: false };

/** Drag to move a node; the node stays pinned where it is dropped. */
function bindDragging(app: App, renderer: Sigma): void {
  let dragged: string | null = null;
  renderer.on("downNode", ({ node }) => {
    dragged = node;
    drag.moved = false;
    if (!renderer.getCustomBBox()) renderer.setCustomBBox(renderer.getBBox());
  });
  renderer.on("moveBody", ({ event }) => {
    if (!dragged) return;
    drag.moved = true;
    const pos = renderer.viewportToGraph(event);
    app.graph.mergeNodeAttributes(dragged, { x: pos.x, y: pos.y, fixed: true });
    event.preventSigmaDefault();
    event.original.preventDefault();
    event.original.stopPropagation();
  });
  const end = () => {
    if (dragged && drag.moved) app.layout.save();
    dragged = null;
    window.setTimeout(() => (drag.moved = false), 0);
  };
  renderer.on("upNode", end);
  renderer.on("upStage", end);
}

/**
 * Pulses animate every frame for a moment; the activity trail only needs a redraw when it
 * changes phase (hot → warm → gone), so it schedules single frames instead of a loop.
 */
export class Animator {
  private frame = 0;
  private timer: number | undefined;

  constructor(private readonly app: App) {
    document.addEventListener("visibilitychange", () => !document.hidden && this.kick());
  }

  kick(): void {
    if (this.frame) return;
    window.clearTimeout(this.timer);
    this.frame = requestAnimationFrame(() => this.tick());
  }

  private tick(): void {
    this.frame = 0;
    const { pulses, trail } = this.app.state;
    const now = performance.now();
    for (const [id, t] of pulses) if (now - t > PULSE_MS) pulses.delete(id);
    for (const [id, t] of trail) if (now - t > TRAIL_MS) trail.delete(id);
    this.app.refresh();
    if (pulses.size && !this.app.reducedMotion.matches && !document.hidden) {
      this.frame = requestAnimationFrame(() => this.tick());
      return;
    }
    const upcoming = [
      ...[...pulses.values()].map((t) => t + PULSE_MS + 1),
      ...[...trail.values()].flatMap((t) => [t + TRAIL_HOT_MS + 1, t + TRAIL_MS + 1]),
    ].filter((t) => t > now);
    if (upcoming.length) {
      this.timer = window.setTimeout(() => this.kick(), Math.max(16, Math.min(...upcoming) - now));
    }
  }
}
