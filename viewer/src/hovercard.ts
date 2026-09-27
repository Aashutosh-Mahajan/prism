// Hover card: what a node is, where it lives, and how connected it is — before any click.
import type { App } from "./app";
import { KIND_LABELS } from "./app";
import { $, el, plural } from "./ui";

export class HoverCard {
  private readonly card = $("hovercard");
  private readonly stage = $("stage");
  private current: string | null = null;
  private prefetchTimer: number | undefined;

  constructor(private readonly app: App) {
    const renderer = app.renderer;
    renderer.on("enterNode", ({ node }) => this.show(node));
    renderer.on("leaveNode", () => this.hide());
    renderer.getCamera().on("updated", () => this.current && this.position(this.current));
    renderer.on("downStage", () => this.hide());
  }

  show(id: string): void {
    const n = this.app.node(id);
    if (!n) return;
    this.current = id;
    const incoming = this.app.rel.incoming.get(id)?.length ?? 0;
    const outgoing = this.app.rel.outgoing.get(id)?.length ?? 0;
    const color = this.app.graph.getNodeAttribute(id, "color") as string;
    const pct = this.app.importancePercentile(id);
    const where = n.kind === "cluster" ? plural(n.files ?? 0, "file") : `${n.file ?? ""}${n.lines ? `:${n.lines[0]}` : ""}`;
    const parts: (Node | null)[] = [
      el("div", { class: "hc-kind" }, [el("span", { class: "sw", style: `background:${color}` }), KIND_LABELS[n.kind] ?? n.kind,
        n.entry_point ? " · entry point" : "", n.test ? " · test" : ""]),
      el("div", { class: "hc-name" }, [n.label]),
      where ? el("div", { class: "hc-loc" }, [where]) : null,
      n.doc ? el("div", { class: "hc-doc" }, [n.doc.length > 140 ? `${n.doc.slice(0, 139)}…` : n.doc]) : null,
      el("div", { class: "hc-stats" }, [
        el("span", {}, [el("b", {}, [String(incoming)]), " in"]),
        el("span", {}, [el("b", {}, [String(outgoing)]), " out"]),
        el("span", {}, ["top ", el("b", {}, [`${Math.max(1, 100 - pct)}%`])]),
        n.risk >= 0.35 ? el("span", {}, ["risk ", el("b", {}, [`${Math.round(n.risk * 100)}%`])]) : null,
        n.findings ? el("span", {}, [el("b", {}, [String(n.findings)]), " findings"]) : null,
      ]),
      el("div", { class: "hc-hint" }, [n.kind === "cluster" ? "Click to inspect · double-click to open" : "Click to inspect"]),
    ];
    this.card.replaceChildren(...parts.filter((p): p is Node => p !== null));
    this.card.hidden = false;
    this.position(id);
    window.clearTimeout(this.prefetchTimer);
    // Warm the inspector: details are usually ready by the time the click lands.
    this.prefetchTimer = window.setTimeout(() => this.app.prefetch(id), 160);
  }

  private position(id: string): void {
    const d = this.app.renderer.getNodeDisplayData(id);
    if (!d) return this.hide();
    const p = this.app.renderer.framedGraphToViewport({ x: d.x, y: d.y });
    const size = this.app.renderer.scaleSize(d.size);
    const { width, height } = this.stage.getBoundingClientRect();
    const cw = this.card.offsetWidth;
    const ch = this.card.offsetHeight;
    let x = p.x + size + 14;
    let y = p.y - ch / 2;
    if (x + cw > width - 12) x = p.x - size - 14 - cw;
    y = Math.max(10, Math.min(height - ch - 10, y));
    this.card.style.transform = `translate(${Math.round(Math.max(8, x))}px, ${Math.round(y)}px)`;
    this.card.style.left = "0";
    this.card.style.top = "0";
  }

  hide(): void {
    this.current = null;
    this.card.hidden = true;
    window.clearTimeout(this.prefetchTimer);
  }
}
