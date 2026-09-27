// Toolbar, drawer, canvas pointer/keyboard handling, and saved views.
import type { App, ViewState } from "./app";
import { LEVELS, emptyFilters } from "./app";
import type { ColorBy, SizeBy } from "./encode";
import type { Direction } from "./graph-utils";
import type { NodeList } from "./nodelist";
import { drag } from "./renderer";
import type { Search } from "./search";
import { toggleTheme } from "./theme";
import type { Filters, Layer, Level } from "./types";
import { $, el, store, stored, toast } from "./ui";
import { FILTER_KINDS, parseView, type SavedView } from "./views";

const KIND_CHIP_LABELS: Record<string, string> = {
  cluster: "Packages", module: "Modules", class: "Classes", function: "Functions", method: "Methods", test: "Tests", route: "Routes",
};

function input(id: string): HTMLInputElement {
  return $<HTMLInputElement>(id);
}

export function syncFilterInputs(f: Filters): void {
  input("f-path").value = f.path;
  input("f-hide-tests").checked = f.hide_tests;
  input("f-orphans").checked = f.orphans_only;
  input("f-rank").value = String(f.min_rank);
  input("f-risk").value = String(f.min_risk);
  input("f-changed").value = f.changed_since;
  $("f-rank-out").textContent = String(f.min_rank);
  $("f-risk-out").textContent = String(f.min_risk);
  document.querySelectorAll<HTMLInputElement>("#f-kinds input").forEach((i) => (i.checked = f.kinds.includes(i.value)));
}

function readFilters(): Filters {
  const clamp = (v: number) => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0);
  return {
    path: input("f-path").value.trim(),
    kinds: [...document.querySelectorAll<HTMLInputElement>("#f-kinds input:checked")].map((i) => i.value),
    hide_tests: input("f-hide-tests").checked,
    orphans_only: input("f-orphans").checked,
    min_rank: clamp(Number(input("f-rank").value)),
    min_risk: clamp(Number(input("f-risk").value)),
    changed_since: input("f-changed").value.trim(),
  };
}

async function renderViews(app: App): Promise<void> {
  const list = $("v-list");
  const views = await app.source.views().catch(() => ({}));
  list.replaceChildren();
  const entries = Object.entries(views);
  if (!entries.length) list.append(el("li", { class: "hint" }, ["Saved views keep the level, filters, colours, and camera."]));
  for (const [name, raw] of entries) {
    const view = parseView(raw);
    list.append(el("li", {}, [el("button", {
      type: "button",
      disabled: view === null,
      title: view ? undefined : "This view was saved by an older version and can't be restored",
      onclick: () => view && void applyView(app, view),
    }, [name])]));
  }
}

async function applyView(app: App, v: SavedView): Promise<void> {
  Object.assign(app.state, {
    level: v.level, layer: v.layer, root: v.root, depth: v.depth, filters: v.filters,
    colorBy: v.colorBy, sizeBy: v.sizeBy, drill: v.drill,
  } satisfies Partial<ViewState>);
  syncFilterInputs(v.filters);
  input("depth").value = String(v.depth);
  $("depth-out").textContent = String(v.depth);
  await app.load({ keepCamera: true });
  if (v.camera) void app.renderer.getCamera().animate(v.camera, { duration: 400 });
}

// --- binding --------------------------------------------------------------------------

export function bindControls(app: App, list: NodeList, search: Search): void {
  const s = app.state;
  const renderer = app.renderer;

  // Canvas pointer: click inspects, double-click opens, background click clears.
  renderer.on("clickNode", ({ node }) => {
    if (!drag.moved) app.select(node, { moveCamera: false });
  });
  renderer.on("doubleClickNode", ({ node, event }) => {
    event.preventSigmaDefault();
    app.openNode(node);
  });
  renderer.on("clickStage", () => {
    if (!drag.moved && s.selected) app.closeInspector();
  });
  renderer.on("enterNode", ({ node }) => {
    s.hovered = node;
    $("graph").style.cursor = "pointer";
    app.refresh();
  });
  renderer.on("leaveNode", () => {
    s.hovered = null;
    $("graph").style.cursor = "";
    app.refresh();
  });

  // Canvas keyboard: arrows move focus between nodes, Enter inspects.
  const graphEl = $("graph");
  const arrows: Record<string, Direction> = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  graphEl.addEventListener("keydown", (e) => {
    if (e.key in arrows) {
      e.preventDefault();
      app.moveFocus(arrows[e.key]);
    } else if (e.key === "Enter" && s.focused) {
      e.preventDefault();
      app.select(s.focused, { moveCamera: false, focusPanel: true });
    } else if (e.key === "Enter") {
      app.moveFocus("right");
    }
  });
  graphEl.addEventListener("focus", () => {
    if (!s.focused && app.graph.order) app.moveFocus("right");
  });

  // Toolbar.
  document.querySelectorAll<HTMLButtonElement>("#level button").forEach((b) => {
    b.addEventListener("click", () => app.setLevel(b.dataset.level as Level));
    b.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const idx = LEVELS.indexOf(b.dataset.level as Level);
      const next = LEVELS[(idx + (e.key === "ArrowRight" ? 1 : LEVELS.length - 1)) % LEVELS.length];
      document.querySelector<HTMLButtonElement>(`#level button[data-level="${next}"]`)?.focus();
      app.setLevel(next);
    });
  });
  $<HTMLSelectElement>("layer").addEventListener("change", (e) => {
    s.layer = (e.target as HTMLSelectElement).value as Layer;
    void app.load();
  });
  $<HTMLSelectElement>("color-by").addEventListener("change", (e) => {
    s.colorBy = (e.target as HTMLSelectElement).value as ColorBy;
    if (s.colorBy === "community") app.ensureCommunities();
    app.encode();
    app.renderer.refresh();
  });
  $<HTMLSelectElement>("size-by").addEventListener("change", (e) => {
    s.sizeBy = (e.target as HTMLSelectElement).value as SizeBy;
    app.encode();
    app.renderer.refresh();
  });
  const themeButton = $("theme");
  const labelTheme = () => {
    const other = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    themeButton.title = `Switch to ${other} theme`;
    themeButton.setAttribute("aria-label", themeButton.title);
  };
  labelTheme();
  themeButton.addEventListener("click", () => {
    const theme = toggleTheme();
    labelTheme();
    app.encode();
    app.renderer.refresh();
    toast(`${theme === "light" ? "Light" : "Dark"} theme`);
  });
  $("help").addEventListener("click", () => $<HTMLDialogElement>("help-dialog").showModal());
  const drawer = $("drawer");
  const drawerToggle = $("toggle-drawer");
  // Only an explicit toggle is remembered; the narrow-screen default is not.
  const setDrawer = (open: boolean, remember = false) => {
    drawer.classList.toggle("collapsed", !open);
    drawerToggle.setAttribute("aria-expanded", String(open));
    if (remember) store("prism-drawer", open ? "1" : "0");
  };
  setDrawer(stored("prism-drawer") !== "0" && !matchMedia("(max-width: 900px)").matches);
  drawerToggle.addEventListener("click", () => setDrawer(drawer.classList.contains("collapsed"), true));

  // Drawer tabs (roving tabindex).
  const tabs = [$("tab-nodes"), $("tab-explore")];
  const selectTab = (tab: HTMLElement, focus = false) => {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")!).hidden = !on;
    }
    if (focus) tab.focus();
    store("prism-tab", tab.id);
  };
  for (const t of tabs) {
    t.addEventListener("click", () => selectTab(t));
    t.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") selectTab(tabs[(tabs.indexOf(t) + 1) % tabs.length], true);
    });
  }
  const savedTab = stored("prism-tab");
  if (savedTab === "tab-explore") selectTab(tabs[1]);

  // Filters.
  const kinds = $("f-kinds");
  for (const k of FILTER_KINDS) kinds.append(el("label", {}, [el("input", { type: "checkbox", value: k }), KIND_CHIP_LABELS[k]]));
  for (const id of ["f-rank", "f-risk"]) input(id).addEventListener("input", (e) => ($(`${id}-out`).textContent = (e.target as HTMLInputElement).value));
  const apply = () => {
    s.filters = readFilters();
    void app.load();
  };
  $("f-apply").addEventListener("click", apply);
  for (const id of ["f-hide-tests", "f-orphans"]) input(id).addEventListener("change", apply);
  kinds.addEventListener("change", apply);
  for (const id of ["f-path", "f-changed"]) input(id).addEventListener("keydown", (e) => e.key === "Enter" && apply());
  $("f-reset").addEventListener("click", () => {
    s.filters = emptyFilters();
    s.drill = null;
    syncFilterInputs(s.filters);
    void app.load();
  });

  // Focus (local graph).
  input("depth").addEventListener("input", (e) => {
    s.depth = Number((e.target as HTMLInputElement).value);
    $("depth-out").textContent = String(s.depth);
    if (s.root) void app.load({ keepCamera: true });
  });
  $("local-clear").addEventListener("click", () => app.setRoot(null));

  // Overlays.
  const toggles: [string, (v: boolean) => void][] = [
    ["o-cycles", (v) => (s.showCycles = v)],
    ["o-dead", (v) => (s.showDead = v)],
    ["o-activity", (v) => (s.showActivity = v)],
    ["o-labels", (v) => (s.showLabels = v)],
  ];
  for (const [id, set] of toggles) {
    input(id).addEventListener("change", (e) => {
      set((e.target as HTMLInputElement).checked);
      app.refresh();
      app.emit("view");
    });
  }
  $("o-diff-go").addEventListener("click", () => void app.showDiff(input("o-diff").value.trim()));
  input("o-diff").addEventListener("keydown", (e) => e.key === "Enter" && void app.showDiff(input("o-diff").value.trim()));
  $("o-clear").addEventListener("click", () => app.clearOverlays());

  // Path finder.
  const findPath = async () => {
    const from = input("p-from").value.trim();
    const to = input("p-to").value.trim();
    if (!from || !to) {
      $("p-info").textContent = "Enter both ends, e.g. a file path or a symbol name.";
      return;
    }
    try {
      $("p-info").textContent = await app.findPath(from, to);
    } catch (err) {
      $("p-info").textContent = err instanceof Error ? err.message : String(err);
    }
  };
  $("p-go").addEventListener("click", () => void findPath());
  for (const id of ["p-from", "p-to"]) input(id).addEventListener("keydown", (e) => e.key === "Enter" && void findPath());

  // Layout.
  input("ph-run").addEventListener("change", (e) => {
    const on = (e.target as HTMLInputElement).checked;
    app.layout.frozen = !on;
    if (on) app.layout.start();
    else app.layout.stop(true);
  });
  for (const id of ["ph-gravity", "ph-scaling", "ph-weight", "ph-slow"]) {
    input(id).addEventListener("input", (e) => {
      $(`${id}-out`).textContent = (e.target as HTMLInputElement).value;
      app.layout.retune();
    });
  }
  for (const id of ["ph-linlog", "ph-strong"]) input(id).addEventListener("change", () => app.layout.retune());
  $("ph-reset").addEventListener("click", () => app.layout.rearrange());
  $("ph-unpin").addEventListener("click", () => app.layout.unpinAll());

  // Saved views.
  const saveView = async () => {
    const name = input("v-name").value.trim();
    if (!/^[A-Za-z0-9 _.-]{1,64}$/.test(name)) {
      toast("Use 1–64 letters, digits, spaces, dots, dashes, or underscores for the view name.", true);
      return;
    }
    const view: SavedView = {
      level: s.level, layer: s.layer, root: s.root, depth: s.depth, filters: s.filters,
      colorBy: s.colorBy, sizeBy: s.sizeBy, drill: s.drill, camera: app.renderer.getCamera().getState(),
    };
    try {
      await app.source.saveView(name, view);
      toast(`Saved view “${name}”`);
      input("v-name").value = "";
      await renderViews(app);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), true);
    }
  };
  $("v-save").addEventListener("click", () => void saveView());
  input("v-name").addEventListener("keydown", (e) => e.key === "Enter" && void saveView());
  void renderViews(app);

  // Inspector close.
  $("panel-close").addEventListener("click", () => app.closeInspector());
  $("panel").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      app.closeInspector();
    }
  });

  // Global shortcuts (ignored while typing).
  document.addEventListener("keydown", (e) => {
    const target = e.target;
    const typing = target instanceof HTMLElement && (target.matches("input, select, textarea") || target.isContentEditable);
    if (e.key === "/" && !typing) {
      e.preventDefault();
      search.focus();
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey || $<HTMLDialogElement>("help-dialog").open) return;
    const inList = target instanceof HTMLElement && target.closest("#node-list");
    switch (e.key) {
      case "Escape":
        app.clearOverlays();
        if (s.selected) app.closeInspector();
        else if (s.focused) app.setFocus(null, false);
        break;
      case "l": case "L":
        if (s.selected ?? s.focused) app.setRoot(s.selected ?? s.focused);
        break;
      case "b": case "B":
        if (s.selected ?? s.focused) void app.showBlast((s.selected ?? s.focused)!);
        break;
      case "n": case "N":
        setDrawer(true, true);
        selectTab(tabs[0]);
        list.focus();
        break;
      case "?": $<HTMLDialogElement>("help-dialog").showModal(); break;
      case "1": app.setLevel("package"); break;
      case "2": app.setLevel("file"); break;
      case "3": app.setLevel("symbol"); break;
      case "+": case "=": app.zoom(1); break;
      case "-": app.zoom(-1); break;
      case "0": app.fit(); break;
      case " ":
        if (inList) return;
        e.preventDefault();
        if (app.layout.running) app.layout.stop(true);
        else app.layout.start();
        break;
      default:
        return;
    }
  });
  $("zoom-in").addEventListener("click", () => app.zoom(1));
  $("zoom-out").addEventListener("click", () => app.zoom(-1));
  $("zoom-fit").addEventListener("click", () => app.fit());
}
