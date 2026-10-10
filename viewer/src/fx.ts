// The light layer, drawn between edges and nodes: a spectral ring around the selected node,
// light flowing along its links in the direction of the dependency, a beam along a found path,
// ripples for blast radius and live updates, the burst a view blooms out of, and the tier bands
// of the architecture layout. It only animates while something is lit; with reduced motion it
// draws still frames.
import type Sigma from "sigma";

import type { App } from "./app";
import { bandLabel } from "./layered";
import { PULSE_MS } from "./renderer";
import { palette, withAlpha } from "./theme";

const SPECTRUM = ["#ff6b8b", "#ffa45c", "#ffe066", "#5ee6a8", "#4cc9f0", "#7b8cff", "#c77dff", "#ff6b8b"];
const MAX_FLOW_EDGES = 260;
const RIPPLE_MS = 1700;
const BURST_MS = 900;
const LABEL_FONT = '"Prism Mono", "JetBrains Mono", Consolas, monospace';

type Pt = { x: number; y: number };

export class Fx {
  private readonly ctx: CanvasRenderingContext2D;
  private readonly canvas: HTMLCanvasElement;
  private frame = 0;
  private ripple: { id: string; start: number } | null = null;
  private burst: { at: Pt; start: number } | null = null;

  constructor(private readonly app: App, private readonly renderer: Sigma) {
    // Typed as style-only, but the options are passed to createCanvas, which places the layer.
    renderer.createCanvasContext("fx", { beforeLayer: "nodes" } as never);
    renderer.resize(true);
    this.canvas = renderer.getCanvases().fx;
    this.ctx = this.canvas.getContext("2d")!;
    renderer.on("afterRender", () => this.draw());
    document.addEventListener("visibilitychange", () => !document.hidden && this.kick());
  }

  /** A ripple of what depends on `id` (blast radius) spreading outward. */
  rippleFrom(id: string): void {
    this.ripple = { id, start: performance.now() };
    this.kick();
  }

  /** The point a view blooms out of (graph coordinates). */
  burstAt(at: Pt): void {
    this.burst = { at, start: performance.now() };
    this.kick();
  }

  kick(): void {
    if (!this.frame) this.frame = requestAnimationFrame(this.loop);
  }

  private loop = (): void => {
    this.frame = 0;
    this.draw();
    if (this.animating() && !document.hidden) this.frame = requestAnimationFrame(this.loop);
  };

  private animating(): boolean {
    if (this.app.reducedMotion.matches) return false;
    const s = this.app.state;
    const now = performance.now();
    return Boolean(
      s.selected || s.path ||
      (this.ripple && now - this.ripple.start < RIPPLE_MS) ||
      (this.burst && now - this.burst.start < BURST_MS) ||
      s.pulses.size,
    );
  }

  private point(id: string): (Pt & { r: number }) | null {
    const d = this.renderer.getNodeDisplayData(id);
    if (!d || d.hidden) return null;
    const p = this.renderer.framedGraphToViewport({ x: d.x, y: d.y });
    return { x: p.x, y: p.y, r: this.renderer.scaleSize(d.size) };
  }

  draw(): void {
    const { ctx, canvas } = this;
    const ratio = canvas.width / Math.max(1, canvas.clientWidth || 1);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, canvas.width / ratio, canvas.height / ratio);
    const now = performance.now();
    const still = this.app.reducedMotion.matches;
    this.drawBands();
    this.drawBurst(now);
    const s = this.app.state;
    if (s.path) this.drawFlows(this.pathEdges(), now, still, true);
    // Light flows only along the selected node's links (hover stays calm, as in Obsidian).
    const focus = !s.rings && !s.path && !s.diff ? s.selected : null;
    if (focus && (!s.hovered || s.hovered === focus)) this.drawFlows(this.edgesOf(focus), now, still, false);
    for (const [id, t] of s.pulses) this.drawShock(id, now - t);
    this.drawRipple(now, still);
    if (s.hovered && s.hovered !== s.selected) this.drawHalo(s.hovered, 0.35);
    if (s.selected) this.drawSelection(s.selected, now, still);
  }

  private edgesOf(id: string): [string, string][] {
    const out: [string, string][] = [];
    for (const t of this.app.rel.outgoing.get(id) ?? []) out.push([id, t]);
    for (const s of this.app.rel.incoming.get(id) ?? []) out.push([s, id]);
    return out.slice(0, MAX_FLOW_EDGES);
  }

  private pathEdges(): [string, string][] {
    const nodes = [...(this.app.state.path ?? [])];
    const edges: [string, string][] = [];
    for (const key of this.app.state.pathEdges) {
      const [a, b] = key.split("\u0000");
      if (a && b) edges.push([a, b]);
    }
    return edges.length ? edges : nodes.slice(1).map((n, i) => [nodes[i], n]);
  }

  /** The route a link is drawn along, in viewport pixels. */
  private route(source: string, target: string): Pt[] {
    const a = this.point(source);
    const b = this.point(target);
    return a && b ? [a, b] : [];
  }

  /** Light travelling from the dependent to what it depends on, coloured by its source. */
  private drawFlows(edges: [string, string][], now: number, still: boolean, beam: boolean): void {
    const { ctx } = this;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (const [source, target] of edges) {
      const pts = this.route(source, target);
      if (pts.length < 2) continue;
      const lengths = [0];
      for (let i = 1; i < pts.length; i++) lengths.push(lengths[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
      const len = lengths[lengths.length - 1];
      if (len < 4) continue;
      const color = beam ? "#ffffff" : this.colorOf(source);
      const a = pts[0];
      const b = pts[pts.length - 1];
      // A faint lit core along the link itself.
      const grad = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
      grad.addColorStop(0, withAlpha(color, beam ? 0.5 : 0.3));
      grad.addColorStop(1, withAlpha(color, beam ? 0.5 : 0.1));
      ctx.strokeStyle = grad;
      ctx.lineWidth = beam ? 2.4 : 1.4;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      for (const p of pts.slice(1)) ctx.lineTo(p.x, p.y);
      ctx.stroke();
      if (still) continue;
      const count = Math.max(1, Math.min(5, Math.round(len / 90)));
      const speed = beam ? 0.0009 : 0.00055;
      const period = Math.max(0.6, len / 220);
      for (let i = 0; i < count; i++) {
        const phase = ((now * speed) / period + i / count) % 1;
        const at = alongPolyline(pts, lengths, phase * len);
        dot(ctx, at.x, at.y, beam ? 3 : 2.2, color, 0.85 * Math.sin(phase * Math.PI));
      }
    }
    ctx.restore();
  }

  private drawSelection(id: string, now: number, still: boolean): void {
    const p = this.point(id);
    if (!p) return;
    const { ctx } = this;
    this.drawHalo(id, 1);
    const r = p.r + 7;
    const turn = still ? 0 : (now / 2400) % (Math.PI * 2);
    ctx.save();
    const conic = ctx.createConicGradient(turn, p.x, p.y);
    SPECTRUM.forEach((c, i) => conic.addColorStop(i / (SPECTRUM.length - 1), c));
    ctx.strokeStyle = conic;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.stroke();
    // A thin outer orbit with one bright mote.
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r + 7, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
    if (!still) {
      const a = -turn * 1.7;
      ctx.globalCompositeOperation = "lighter";
      dot(ctx, p.x + Math.cos(a) * (r + 7), p.y + Math.sin(a) * (r + 7), 2.6, "#ffffff", 0.95);
    }
    ctx.restore();
  }

  private drawHalo(id: string, strength: number): void {
    const p = this.point(id);
    if (!p) return;
    const { ctx } = this;
    const color = this.colorOf(id);
    const r = p.r * 2.6 + 18;
    const g = ctx.createRadialGradient(p.x, p.y, p.r * 0.6, p.x, p.y, r);
    g.addColorStop(0, withAlpha(color, 0.32 * strength));
    g.addColorStop(1, withAlpha(color, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  private drawShock(id: string, age: number): void {
    if (age > PULSE_MS) return;
    const p = this.point(id);
    if (!p) return;
    const t = age / PULSE_MS;
    const { ctx } = this;
    ctx.save();
    ctx.strokeStyle = withAlpha(palette.accent || "#ffffff", 0.7 * (1 - t));
    ctx.lineWidth = 2 * (1 - t) + 0.5;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r + 4 + t * 46, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  private drawRipple(now: number, still: boolean): void {
    const r = this.ripple;
    if (!r || !this.app.state.rings) return;
    const p = this.point(r.id);
    if (!p) return;
    const age = still ? RIPPLE_MS * 0.35 : now - r.start;
    if (age > RIPPLE_MS) return;
    const { ctx } = this;
    ctx.save();
    for (let wave = 0; wave < 3; wave++) {
      const t = (age - wave * 220) / (RIPPLE_MS - 440);
      if (t <= 0 || t >= 1) continue;
      ctx.strokeStyle = withAlpha(palette.rings[1 + wave] || "#ff8a9a", 0.6 * (1 - t));
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r + 6 + t * Math.min(420, this.canvas.clientWidth * 0.35), 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawBurst(now: number): void {
    const b = this.burst;
    if (!b) return;
    const age = now - b.start;
    if (age > BURST_MS) {
      this.burst = null;
      return;
    }
    const p = this.renderer.graphToViewport(b.at);
    const t = age / BURST_MS;
    const { ctx } = this;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const r = 20 + t * 260;
    const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
    g.addColorStop(0, `rgba(255,255,255,${0.55 * (1 - t)})`);
    g.addColorStop(0.35, `rgba(150,170,255,${0.18 * (1 - t)})`);
    g.addColorStop(1, "rgba(150,170,255,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    // The spectrum fanning out of the light.
    const conic = ctx.createConicGradient(t * 2, p.x, p.y);
    SPECTRUM.forEach((c, i) => conic.addColorStop(i / (SPECTRUM.length - 1), c));
    ctx.globalAlpha = 0.5 * (1 - t);
    ctx.strokeStyle = conic;
    ctx.lineWidth = 3 * (1 - t) + 0.5;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 10 + t * 180, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  /** Architecture layout: one band per dependency tier, labelled at the left edge. */
  private drawBands(): void {
    const bands = this.app.bands;
    if (!bands.length || this.app.state.layoutMode !== "layers") return;
    const { ctx } = this;
    const width = this.canvas.clientWidth;
    const tiers = this.app.payload?.tiers ?? 0;
    ctx.save();
    ctx.font = `600 10px ${LABEL_FONT}`;
    ctx.textBaseline = "middle";
    bands.forEach((band, i) => {
      const top = this.renderer.graphToViewport({ x: 0, y: band.top }).y;
      const bottom = this.renderer.graphToViewport({ x: 0, y: band.bottom }).y;
      const y0 = Math.min(top, bottom);
      const h = Math.max(14, Math.abs(bottom - top));
      if (i % 2 === 0) {
        ctx.fillStyle = withAlpha(palette.label || "#ffffff", 0.025);
        ctx.fillRect(0, y0, width, h);
      }
      ctx.strokeStyle = withAlpha(palette.label || "#ffffff", 0.06);
      ctx.beginPath();
      ctx.moveTo(0, y0 + h);
      ctx.lineTo(width, y0 + h);
      ctx.stroke();
      // The label sits just left of the band's first node, or at the edge if that is off-screen.
      const label = `${bandLabel(band.tier, tiers).toUpperCase()} · ${band.count}`;
      const anchor = this.renderer.graphToViewport({ x: band.left, y: (band.top + band.bottom) / 2 });
      const w = ctx.measureText(label).width;
      const x = Math.max(14, anchor.x - 22 - w);
      ctx.fillStyle = withAlpha(palette.label || "#ffffff", 0.5);
      ctx.fillText(label, x, anchor.y);
    });
    ctx.restore();
  }

  private colorOf(id: string): string {
    return this.app.graph.hasNode(id) ? (this.app.graph.getNodeAttribute(id, "color") as string) : "#ffffff";
  }
}

function dot(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, color: string, alpha: number): void {
  const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3.2);
  g.addColorStop(0, withAlpha("#ffffff", alpha));
  g.addColorStop(0.3, withAlpha(color, alpha * 0.9));
  g.addColorStop(1, withAlpha(color, 0));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r * 3.2, 0, Math.PI * 2);
  ctx.fill();
}

/** The point `distance` pixels along a polyline whose cumulative lengths are given. */
function alongPolyline(pts: Pt[], lengths: number[], distance: number): Pt {
  for (let i = 1; i < pts.length; i++) {
    if (lengths[i] >= distance) {
      const span = lengths[i] - lengths[i - 1] || 1;
      const t = (distance - lengths[i - 1]) / span;
      return { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * t, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * t };
    }
  }
  return pts[pts.length - 1];
}
