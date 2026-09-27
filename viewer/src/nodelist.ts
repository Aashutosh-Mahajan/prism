// Accessible alternative to the canvas: every node in the current view as a keyboard-operable
// listbox. Virtualised (only visible rows exist), so thousands of nodes stay smooth.
import type { App } from "./app";
import { KIND_LABELS } from "./app";
import type { GNode } from "./types";
import { $, el, plural } from "./ui";

const ROW = 40;
const OVERSCAN = 8;
type SortKey = "rank" | "fan_in" | "risk" | "loc" | "name";

export class NodeList {
  private readonly box = $("node-list");
  private readonly spacer = $("node-list-spacer");
  private readonly filterInput = $<HTMLInputElement>("list-filter");
  private readonly sortSelect = $<HTMLSelectElement>("list-sort");
  private rows: GNode[] = [];
  private active = -1;
  private frame = 0;

  constructor(private readonly app: App) {
    app.on("graph", () => this.rebuild());
    app.on("selection", () => this.syncSelection());
    this.box.addEventListener("scroll", () => this.schedule(), { passive: true });
    new ResizeObserver(() => this.schedule()).observe(this.box);
    this.filterInput.addEventListener("input", () => this.rebuild());
    this.filterInput.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        this.box.focus();
        this.setActive(Math.max(0, this.active));
      }
    });
    this.sortSelect.addEventListener("change", () => this.rebuild());
    this.box.addEventListener("keydown", (e) => this.onKey(e));
    this.box.addEventListener("focus", () => {
      if (this.active < 0 && this.rows.length) this.setActive(0);
    });
    this.box.addEventListener("click", (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>(".node-row");
      if (!row) return;
      const index = Number(row.dataset.index);
      this.setActive(index);
      this.choose();
    });
    this.box.addEventListener("mouseover", (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>(".node-row");
      const id = row ? this.rows[Number(row.dataset.index)]?.id ?? null : null;
      if (app.state.hovered !== id) {
        app.state.hovered = id;
        app.refresh();
      }
    });
    this.box.addEventListener("mouseleave", () => {
      app.state.hovered = null;
      app.refresh();
    });
  }

  focus(): void {
    this.box.focus();
  }

  private metric(n: GNode, key: SortKey): string {
    if (key === "fan_in") return `${n.fan_in ?? 0} in`;
    if (key === "risk") return `${Math.round(n.risk * 100)}%`;
    if (key === "loc") return `${n.loc} ln`;
    return `top ${Math.max(1, 100 - this.app.importancePercentile(n.id))}%`;
  }

  rebuild(): void {
    const payload = this.app.payload;
    const key = this.sortSelect.value as SortKey;
    const needle = this.filterInput.value.trim().toLowerCase();
    const nodes = payload?.nodes ?? [];
    this.rows = nodes.filter((n) => !needle || n.id.toLowerCase().includes(needle) || n.label.toLowerCase().includes(needle));
    const by: Record<SortKey, (a: GNode, b: GNode) => number> = {
      rank: (a, b) => b.rank - a.rank,
      fan_in: (a, b) => (b.fan_in ?? 0) - (a.fan_in ?? 0),
      risk: (a, b) => b.risk - a.risk,
      loc: (a, b) => b.loc - a.loc,
      name: () => 0,
    };
    this.rows.sort((a, b) => by[key](a, b) || a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
    $("node-count").textContent = nodes.length ? nodes.length.toLocaleString() : "";
    this.spacer.style.height = `${this.rows.length * ROW}px`;
    this.box.setAttribute("aria-label", `Nodes in the current view, ${this.rows.length} shown, sorted by ${this.sortSelect.selectedOptions[0]?.text.toLowerCase()}`);
    const selected = this.app.state.selected;
    this.active = selected ? this.rows.findIndex((n) => n.id === selected) : -1;
    this.render();
  }

  private schedule(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.render();
    });
  }

  private render(): void {
    const top = this.box.scrollTop;
    const height = this.box.clientHeight || 600;
    const first = Math.max(0, Math.floor(top / ROW) - OVERSCAN);
    const last = Math.min(this.rows.length, Math.ceil((top + height) / ROW) + OVERSCAN);
    const selected = this.app.state.selected;
    const key = this.sortSelect.value as SortKey;
    const fragment = document.createDocumentFragment();
    const indices: number[] = [];
    for (let i = first; i < last; i++) indices.push(i);
    if (this.active >= 0 && (this.active < first || this.active >= last)) indices.push(this.active);
    for (const i of indices) {
      const n = this.rows[i];
      const color = this.app.graph.hasNode(n.id) ? (this.app.graph.getNodeAttribute(n.id, "color") as string) : "var(--dim)";
      const shape = n.kind === "module" ? "square" : n.kind === "cluster" || n.kind === "class" || n.kind === "test" || n.kind === "route" ? "ring" : "";
      const sub = `${KIND_LABELS[n.kind] ?? n.kind}${n.kind === "cluster" ? ` · ${plural(n.files ?? 0, "file")}` : n.file ? ` · ${n.file}` : ""}`;
      const row = el("div", {
        class: `node-row${i === this.active ? " focused" : ""}`,
        role: "option",
        id: `node-opt-${i}`,
        "data-index": String(i),
        "aria-selected": String(n.id === selected),
        "aria-setsize": String(this.rows.length),
        "aria-posinset": String(i + 1),
        style: `top:${i * ROW}px`,
        title: n.id,
      }, [
        el("span", { class: `mark ${shape}`, style: `background:${color};color:${color}`, "aria-hidden": "true" }),
        el("span", { class: "name" }, [n.label]),
        el("span", { class: "metric", "aria-hidden": "true" }, [this.metric(n, key)]),
        el("span", { class: "sub" }, [sub]),
      ]);
      fragment.append(row);
    }
    this.spacer.replaceChildren(fragment);
    if (this.active >= 0) this.box.setAttribute("aria-activedescendant", `node-opt-${this.active}`);
    else this.box.removeAttribute("aria-activedescendant");
  }

  private setActive(index: number, scroll = true): void {
    if (!this.rows.length) return;
    this.active = Math.max(0, Math.min(this.rows.length - 1, index));
    if (scroll) {
      const top = this.active * ROW;
      if (top < this.box.scrollTop) this.box.scrollTop = top;
      else if (top + ROW > this.box.scrollTop + this.box.clientHeight) this.box.scrollTop = top + ROW - this.box.clientHeight;
    }
    const id = this.rows[this.active].id;
    this.app.state.hovered = id;
    this.app.refresh();
    this.render();
  }

  private choose(): void {
    const n = this.rows[this.active];
    if (n) this.app.select(n.id, { moveCamera: true });
  }

  private onKey(e: KeyboardEvent): void {
    const page = Math.max(1, Math.floor(this.box.clientHeight / ROW) - 1);
    const moves: Record<string, number> = {
      ArrowDown: this.active + 1, ArrowUp: this.active - 1, PageDown: this.active + page,
      PageUp: this.active - page, Home: 0, End: this.rows.length - 1,
    };
    if (e.key in moves) {
      e.preventDefault();
      this.setActive(moves[e.key]);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      this.choose();
    } else if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Type to filter.
      this.filterInput.focus();
      this.filterInput.value += e.key;
      this.filterInput.dispatchEvent(new Event("input"));
      e.preventDefault();
    }
  }

  private syncSelection(): void {
    const selected = this.app.state.selected;
    if (selected) {
      const index = this.rows.findIndex((n) => n.id === selected);
      if (index >= 0) {
        this.active = index;
        const top = index * ROW;
        if (top < this.box.scrollTop || top + ROW > this.box.scrollTop + this.box.clientHeight) {
          this.box.scrollTop = Math.max(0, top - this.box.clientHeight / 2);
        }
      }
    }
    this.render();
  }
}
