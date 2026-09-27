// Search box (combobox pattern): debounced, stale responses ignored, arrow keys and Enter.
import type { App } from "./app";
import { KIND_LABELS } from "./app";
import { kindColor } from "./encode";
import { RequestGeneration } from "./graph-utils";
import type { SearchHit } from "./types";
import { $, announce, el, plural, toast } from "./ui";

export class Search {
  private readonly input = $<HTMLInputElement>("search");
  private readonly results = $("search-results");
  private readonly requests = new RequestGeneration();
  private hits: SearchHit[] = [];
  private active = 0;
  private timer: number | undefined;
  private query = "";

  constructor(private readonly app: App) {
    this.input.addEventListener("input", () => this.onInput());
    this.input.addEventListener("keydown", (e) => this.onKey(e));
    this.input.addEventListener("focus", () => this.hits.length && this.render());
    this.input.addEventListener("blur", () => window.setTimeout(() => {
      if (document.activeElement !== this.input) this.close();
    }, 120));
  }

  focus(): void {
    this.input.focus();
    this.input.select();
  }

  private close(): void {
    this.results.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
  }

  private onInput(): void {
    window.clearTimeout(this.timer);
    const request = this.requests.next();
    const q = this.input.value.trim();
    if (!q) {
      this.hits = [];
      this.query = "";
      this.close();
      return;
    }
    this.timer = window.setTimeout(async () => {
      try {
        const hits = await this.app.source.search(q, this.app.state.level);
        if (!this.requests.current(request)) return;
        this.hits = hits;
        this.query = q;
        this.active = 0;
        this.render();
        announce(hits.length ? `${plural(hits.length, "result")} for ${q}.` : `No results for ${q}.`);
      } catch (err) {
        if (this.requests.current(request)) toast(err instanceof Error ? err.message : String(err), true);
      }
    }, 140);
  }

  private render(): void {
    this.results.replaceChildren();
    this.results.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
    if (!this.hits.length) {
      this.results.append(el("li", { class: "empty-hit", role: "option", "aria-disabled": "true" }, [
        `No code matches “${this.query}”. Try part of a name, a file path, or a word from a docstring.`,
      ]));
      this.input.removeAttribute("aria-activedescendant");
      return;
    }
    this.hits.forEach((h, i) => {
      const where = h.file && h.kind !== "file" ? h.file : "";
      const li = el("li", { id: `search-hit-${i}`, role: "option", "aria-selected": String(i === this.active) }, [
        el("span", { class: "kind-dot", style: `background:${kindColor(h.kind)}`, "aria-hidden": "true" }),
        el("span", { class: "hit-id" }, [h.id]),
        el("span", { class: "hit-meta" }, [[KIND_LABELS[h.kind] ?? h.kind, where, h.snippet].filter(Boolean).join(" · ")]),
      ]);
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        this.choose(h);
      });
      this.results.append(li);
    });
    this.input.setAttribute("aria-activedescendant", `search-hit-${this.active}`);
    document.getElementById(`search-hit-${this.active}`)?.scrollIntoView({ block: "nearest" });
  }

  private onKey(e: KeyboardEvent): void {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!this.hits.length) return;
      e.preventDefault();
      this.active = (this.active + (e.key === "ArrowDown" ? 1 : -1) + this.hits.length) % this.hits.length;
      this.render();
    } else if (e.key === "Enter" && this.hits[this.active]) {
      e.preventDefault();
      this.choose(this.hits[this.active]);
    } else if (e.key === "Escape") {
      this.requests.next();
      this.close();
      this.input.blur();
      $("graph").focus();
    }
  }

  private choose(h: SearchHit): void {
    this.requests.next();
    window.clearTimeout(this.timer);
    this.close();
    const target = h.node ?? h.id;
    if (this.app.graph.hasNode(target)) {
      this.app.select(target, { focusPanel: true });
      return;
    }
    // Not in the current view: open its neighbourhood so it is.
    this.app.state.root = h.id;
    void this.app.load().then((ok) => {
      const found = ok ? this.app.mapToNode(target) ?? this.app.mapToNode(h.id) : null;
      if (found) this.app.select(found, { focusPanel: true });
    });
  }
}
