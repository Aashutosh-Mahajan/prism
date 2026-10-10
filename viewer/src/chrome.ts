// View chrome around the canvas: scope line and breadcrumbs, legend/encoding card, empty
// state, and status bar. All of it re-renders from app state on "view" and "graph" events.
import type { App } from "./app";
import { LAYER_LABELS, LEVEL_LABELS, emptyFilters } from "./app";
import { COLOR_BY_LABELS, SIZE_BY_LABELS, legend } from "./encode";
import { $, el, plural, store, stored } from "./ui";

const EDGE_MEANING = {
  import: "Arrow points to what is imported",
  call: "Arrow points to what is called",
  tests: "Arrow points from a test to the code it tests",
  cochange: "Linked files are often changed in the same commit",
  routes: "Route → handler → models it touches",
};

export function bindChrome(app: App): void {
  const toggle = $("encoding-toggle");
  const body = $("encoding-body");
  const setOpen = (open: boolean, remember = false) => {
    toggle.setAttribute("aria-expanded", String(open));
    body.hidden = !open;
    if (remember) store("prism-legend", open ? "1" : "0");
  };
  // Open by default only when the canvas has room for it; an explicit toggle is remembered.
  const roomy = () => $("stage").clientWidth >= 820;
  // Closed unless asked for: the Overview already names the colours, and the canvas needs the room.
  setOpen(stored("prism-legend") === "1");
  toggle.addEventListener("click", () => setOpen(body.hidden, true));
  // Opening the inspector on a narrow canvas tucks the legend away (not remembered).
  app.on("selection", () => {
    if (app.state.selected && !body.hidden && !roomy() && stored("prism-legend") !== "1") setOpen(false);
  });
  app.on("view", () => renderChrome(app));
  app.on("graph", () => renderChrome(app));
}

function renderScope(app: App): void {
  const s = app.state;
  const p = app.payload;
  $("scope-title").replaceChildren(
    el("b", {}, [LEVEL_LABELS[s.level]]), " · ", LAYER_LABELS[s.layer],
    p ? ` · ${plural(p.counts.nodes, "node")} · ${plural(p.counts.edges, "link")}` : "",
  );
  const crumbs = $("breadcrumb");
  crumbs.replaceChildren();
  const filtered = JSON.stringify(s.filters) !== JSON.stringify(emptyFilters());
  if (s.drill || s.root || filtered) {
    crumbs.append(el("button", {
      type: "button",
      onclick: () => {
        s.drill = null;
        s.root = null;
        s.filters = emptyFilters();
        app.emit("view");
        app.setLevel("package");
      },
    }, ["All packages"]));
    if (s.drill) crumbs.append(el("span", { class: "sep", "aria-hidden": "true" }, ["/"]), el("code", {}, [s.drill]));
    if (s.root) {
      crumbs.append(
        el("span", { class: "sep", "aria-hidden": "true" }, ["/"]),
        el("span", {}, ["around ", el("code", {}, [app.node(s.root)?.label ?? s.root]), ` · ${plural(s.depth, "hop")}`]),
        el("button", { type: "button", title: "Show everything", onclick: () => app.setRoot(null) }, ["Clear focus"]),
      );
    }
    if (filtered && !s.drill) crumbs.append(el("span", { class: "sep" }, ["·"]), el("span", {}, ["filtered"]));
  }
  if (p?.truncated) {
    crumbs.append(el("span", { class: "sep" }, ["·"]), el("span", {}, [`${p.truncated.toLocaleString()} less important nodes hidden`]));
  }
}

function renderLegend(app: App): void {
  const ctx = app.encoding;
  const nodes = app.payload?.nodes ?? [];
  const list = $("legend");
  list.replaceChildren();
  if (ctx) {
    for (const item of legend(app.state.colorBy, nodes, ctx)) {
      list.append(el("li", {}, [el("span", { class: "sw", style: `background:${item.color}`, "aria-hidden": "true" }), el("span", {}, [item.label])]));
    }
  }
  list.setAttribute("aria-label", `Colour shows ${COLOR_BY_LABELS[app.state.colorBy].toLowerCase()}`);
  const shapes = $("shapes");
  shapes.replaceChildren();
  const add = (cls: string, text: string) => shapes.append(el("div", {}, [el("span", { class: `shape ${cls}`, "aria-hidden": "true" }), text]));
  add("edge", EDGE_MEANING[app.state.layer]);
  if (app.state.layoutMode === "layers" && app.payload?.tiers) add("edge", "Bands: what depends on more sits higher");
  if (app.state.layer === "call") add("edge weak", "Faint: inferred, lower-confidence call");
  if (app.state.layer === "import" && app.state.showCycles) add("edge cycle", "Red: part of an import cycle");
  shapes.append(el("div", { class: "dim" }, [`Larger = higher ${SIZE_BY_LABELS[app.state.sizeBy].toLowerCase()}`]));
}

function renderEmpty(app: App): void {
  const p = app.payload;
  const empty = $("empty");
  empty.hidden = !p || p.nodes.length > 0;
  if (!p || p.nodes.length) return;
  const s = app.state;
  const filtered = JSON.stringify(s.filters) !== JSON.stringify(emptyFilters());
  $("empty-title").textContent = filtered ? "Nothing matches these filters" : "Nothing to show in this view";
  $("empty-body").textContent = filtered
    ? "Loosen or reset the filters to bring nodes back."
    : `This project has no ${LAYER_LABELS[s.layer].toLowerCase()} at the ${LEVEL_LABELS[s.level].toLowerCase()} level. Try another layer.`;
  const action = $<HTMLButtonElement>("empty-action");
  action.textContent = filtered ? "Reset filters" : "Show imports";
  action.onclick = () => {
    if (filtered) s.filters = emptyFilters();
    else s.layer = "import";
    app.emit("view");
    void app.load();
  };
}

export function renderChrome(app: App): void {
  const s = app.state;
  document.querySelectorAll<HTMLButtonElement>("#level button").forEach((b) =>
    b.setAttribute("aria-checked", String(b.dataset.level === s.level)),
  );
  $<HTMLSelectElement>("layer").value = s.layer;
  $<HTMLSelectElement>("color-by").value = s.colorBy;
  $<HTMLSelectElement>("size-by").value = s.sizeBy;
  const directed = Boolean(app.payload?.tiers);
  document.querySelectorAll<HTMLButtonElement>("#layout-mode button").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.mode === s.layoutMode));
    if (b.dataset.mode === "layers") b.disabled = !directed;
  });
  const p = app.payload;
  $("counts").textContent = p ? `${plural(p.counts.nodes, "node")} · ${plural(p.counts.edges, "link")}` : "";
  $("local-info").textContent = s.root
    ? `Showing ${plural(s.depth, "hop")} around ${app.node(s.root)?.label ?? s.root}.`
    : "Select a node, then press L to show only its neighbourhood.";
  renderScope(app);
  renderLegend(app);
  renderEmpty(app);
}
