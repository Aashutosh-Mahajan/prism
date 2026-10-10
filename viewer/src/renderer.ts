// Sigma (WebGL) renderer: node/edge programs, labels, and the reducers that turn view state
// (hover, selection, keyboard focus, overlays, live activity) into what is drawn.
import { createNodeBorderProgram } from "@sigma/node-border";
import { NodeSquareProgram } from "@sigma/node-square";
import Sigma from "sigma";
import { EdgeArrowProgram, EdgeRectangleProgram } from "sigma/rendering";

import { labelThreshold, type App } from "./app";
import { edgeKey } from "./graph-utils";
import { palette, withAlpha } from "./theme";

export const TRAIL_MS = 20_000;
const TRAIL_HOT_MS = 4_000;
export const PULSE_MS = 2_400;
const LABEL_FONT = '"Prism Mono", "JetBrains Mono", Consolas, monospace';

type Ctx = CanvasRenderingContext2D;
interface Drawn { x: number; y: number; size: number; label?: string | null; color: string; focusRing?: boolean }

/** Obsidian-style label: centred under the node, fading in as the node grows on screen. */
function drawLabel(ctx: Ctx, d: Drawn, textFade: number, weight = 400): void {
  if (!d.label) return;
  const alpha = weight > 400 ? 1 : Math.max(0, Math.min(1, (d.size - (labelThreshold(textFade) - 3)) / 3));
  if (alpha <= 0.02) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = `${weight} 11px ${LABEL_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.lineWidth = 3;
  ctx.lineJoin = "round";
  ctx.strokeStyle = palette.canvas;
  ctx.fillStyle = palette.label;
  const y = d.y + d.size + 4;
  ctx.strokeText(d.label, d.x, y);
  ctx.fillText(d.label, d.x, y);
  ctx.restore();
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
  drawLabel(ctx, d, 0, 600);
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
    edgeProgramClasses: { arrow: EdgeArrowProgram, line: EdgeRectangleProgram },
    defaultEdgeType: "arrow",
    renderEdgeLabels: false,
    labelRenderedSizeThreshold: 7,
    labelDensity: 0.7,
    labelGridCellSize: 120,
    labelFont: LABEL_FONT,
    labelSize: 11,
    defaultDrawNodeLabel: (ctx, data) => drawLabel(ctx, data as Drawn, app.display.textFade),
    defaultDrawNodeHover: (ctx, data) => drawHighlight(ctx, data as Drawn),
    zIndex: true,
    allowInvalidContainer: true,
    // Room for the overlays (scope line, arrangement switch, legend) around the fitted graph.
    stagePadding: 56,
    minCameraRatio: 0.02,
    maxCameraRatio: 25,
    nodeReducer: (node, data) => {
      const res: Record<string, unknown> = { ...data };
      const now = performance.now();
      let faded = false;
      // Nodes grow in as a view blooms open.
      res.size = (data.size as number) * app.display.nodeSize;
      const enter = data.enter as number | undefined;
      if (enter !== undefined && enter < 1) res.size = Math.max(0.1, (res.size as number) * enter);

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
      // Links appear once both ends have (nearly) arrived.
      const g = app.graph;
      if (((g.getNodeAttribute(source, "enter") as number | undefined) ?? 1) < 0.85 ||
          ((g.getNodeAttribute(target, "enter") as number | undefined) ?? 1) < 0.85) {
        res.hidden = true;
        return res;
      }
      res.color = data.confidence === "low" ? app.edgeTint.weak || palette.edgeWeak : app.edgeTint.strong || palette.edge;
      res.size = ((data.size as number) ?? 1) * 0.7 * app.display.linkThickness;

      // Cycles are flagged, not shouted: at package level many links can be part of one.
      if (s.showCycles && data.cycle) res.color = withAlpha(palette.danger, 0.42);
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

/**
 * Drag a node as in Obsidian: in the graph layout it follows the pointer while the simulation
 * pulls its neighbours along, and is let go on release; in the layers layout it simply moves.
 */
function bindDragging(app: App, renderer: Sigma): void {
  let dragged: string | null = null;
  renderer.on("downNode", ({ node }) => {
    app.motion.cancel();
    dragged = node;
    drag.moved = false;
    // Hold the frame still while dragging, so the node stays under the pointer.
    if (!renderer.getCustomBBox()) renderer.setCustomBBox(renderer.getBBox());
  });
  renderer.on("moveBody", ({ event }) => {
    if (!dragged) return;
    if (!drag.moved) app.layout.grab(dragged);
    drag.moved = true;
    const pos = renderer.viewportToGraph(event);
    app.layout.drag(dragged, pos.x, pos.y);
    app.graph.mergeNodeAttributes(dragged, { x: pos.x, y: pos.y });
    event.preventSigmaDefault();
    event.original.preventDefault();
    event.original.stopPropagation();
  });
  const end = () => {
    if (dragged && drag.moved) {
      app.layout.release(dragged);
      app.layout.save();
    }
    if (dragged) renderer.setCustomBBox(null);
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
