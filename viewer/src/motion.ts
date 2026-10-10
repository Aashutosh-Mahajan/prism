// Position tweens for the graph: nodes bloom out of a point when a view opens, fly to their
// place when the layout changes, and grow from nothing when they first appear. One tween at a
// time; a new one (or a drag, or the force layout) takes over from wherever nodes are.
import type { App } from "./app";

export type Point = { x: number; y: number };

export interface TweenOptions {
  duration: number;
  /** Per-node start delay in ms (stagger). */
  delay?: (id: string) => number;
  /** Start positions; nodes without one start where they are. */
  from?: Map<string, Point>;
  /** Nodes that grow in from size 0. */
  entering?: Set<string>;
  onDone?: () => void;
}

export const easeOutExpo = (t: number): number => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));
export const easeOutBack = (t: number): number => {
  const c = 1.55;
  return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2;
};

export class Motion {
  private frame = 0;
  private job: {
    start: number;
    end: number;
    from: Map<string, Point>;
    to: Map<string, Point>;
    opts: TweenOptions;
  } | null = null;

  constructor(private readonly app: App) {
    // Hidden pages get no animation frames: land immediately rather than leave the graph
    // collapsed at its bloom origin until the tab comes back.
    document.addEventListener("visibilitychange", () => document.hidden && this.finish());
  }

  /** Jump to the end of the current tween and run its completion. */
  finish(): void {
    const job = this.job;
    if (!job) return;
    this.cancel(true);
    this.app.refresh();
    job.opts.onDone?.();
  }

  get running(): boolean {
    return this.job !== null;
  }

  tween(to: Map<string, Point>, opts: TweenOptions): void {
    this.cancel(false);
    const g = this.app.graph;
    const instant = this.app.reducedMotion.matches || opts.duration <= 0 || document.hidden;
    if (instant) {
      g.updateEachNodeAttributes((id, a) => {
        const p = to.get(id);
        return p ? { ...a, x: p.x, y: p.y, enter: 1 } : a;
      }, { attributes: ["x", "y"] });
      opts.onDone?.();
      return;
    }
    const from = new Map<string, Point>();
    g.forEachNode((id, a) => from.set(id, opts.from?.get(id) ?? { x: a.x as number, y: a.y as number }));
    let longest = 0;
    for (const id of to.keys()) longest = Math.max(longest, opts.delay?.(id) ?? 0);
    const start = performance.now();
    this.job = { start, end: start + opts.duration + longest, from, to, opts };
    // Frame the destination, not the moving cloud: the camera holds still while nodes travel.
    this.app.renderer.setCustomBBox(bbox(to.values()));
    this.step();
  }

  /** Stop where nodes are now; `settle` jumps them to their destinations. */
  cancel(settle = true): void {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    const job = this.job;
    this.job = null;
    if (!job) return;
    if (settle) this.apply(job, Number.POSITIVE_INFINITY);
    this.app.renderer.setCustomBBox(null);
  }

  private step = (): void => {
    const job = this.job;
    if (!job) return;
    const now = performance.now();
    this.apply(job, now);
    this.app.refresh();
    if (now >= job.end) {
      this.job = null;
      this.app.renderer.setCustomBBox(null);
      job.opts.onDone?.();
      return;
    }
    this.frame = requestAnimationFrame(this.step);
  };

  private apply(job: NonNullable<Motion["job"]>, now: number): void {
    const { from, to, opts, start } = job;
    this.app.graph.updateEachNodeAttributes((id, a) => {
      const target = to.get(id);
      if (!target) return a;
      const origin = from.get(id) ?? target;
      const t = Math.max(0, Math.min(1, (now - start - (opts.delay?.(id) ?? 0)) / opts.duration));
      const e = easeOutExpo(t);
      const next: Record<string, unknown> = { ...a, x: origin.x + (target.x - origin.x) * e, y: origin.y + (target.y - origin.y) * e };
      if (opts.entering?.has(id)) next.enter = Math.max(0.001, easeOutBack(Math.min(1, t * 1.25)));
      else if (a.enter !== undefined && a.enter < 1) next.enter = 1;
      return next;
    }, { attributes: ["x", "y"] });
  }
}

export function bbox(points: Iterable<Point>): { x: [number, number]; y: [number, number] } {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const p of points) {
    if (p.x < x0) x0 = p.x;
    if (p.x > x1) x1 = p.x;
    if (p.y < y0) y0 = p.y;
    if (p.y > y1) y1 = p.y;
  }
  if (!Number.isFinite(x0)) return { x: [-1, 1], y: [-1, 1] };
  if (x1 - x0 < 1e-6) (x0 -= 1), (x1 += 1);
  if (y1 - y0 < 1e-6) (y0 -= 1), (y1 += 1);
  return { x: [x0, x1], y: [y0, y1] };
}
