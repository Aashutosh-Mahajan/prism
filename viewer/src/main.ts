// Entry point: wires the App (state + graph + renderer) to its UI modules and boots.
import "./style.css";

import { App, stateFromUrl } from "./app";
import { bindChrome, renderChrome } from "./chrome";
import { bindControls, syncFilterInputs } from "./controls";
import { createSource } from "./data";
import { HoverCard } from "./hovercard";
import { bindLive } from "./live";
import { NodeList } from "./nodelist";
import { Animator } from "./renderer";
import { Search } from "./search";
import { initTheme, readPalette } from "./theme";
import { $, toast } from "./ui";

async function boot(): Promise<void> {
  initTheme();
  // Canvas labels use the vendored mono face: make sure it is ready before the first draw.
  await Promise.race([
    document.fonts.load('11px "Prism Mono"').catch(() => undefined),
    new Promise((resolve) => window.setTimeout(resolve, 400)),
  ]);
  readPalette();

  const source = createSource();
  const app = new App(source, $("graph"), stateFromUrl(location.search));
  const animator = new Animator(app);
  const list = new NodeList(app);
  const search = new Search(app);
  new HoverCard(app);
  bindChrome(app);
  bindControls(app, list, search);
  syncFilterInputs(app.state.filters);
  $<HTMLInputElement>("depth").value = String(app.state.depth);
  $("depth-out").textContent = String(app.state.depth);
  renderChrome(app);

  try {
    const meta = await source.meta();
    $("project").textContent = meta.project;
    document.title = `${meta.project} · PRISM`;
    $("scan-info").textContent = meta.last_scan ? `Indexed ${new Date(meta.last_scan).toLocaleString()}` : "";
    const layer = $<HTMLSelectElement>("layer");
    if (!meta.has_routes) layer.querySelector('option[value="routes"]')?.setAttribute("disabled", "");
    if (!meta.git) layer.querySelector('option[value="cochange"]')?.setAttribute("disabled", "");
    if (meta.levels) {
      document.querySelectorAll<HTMLButtonElement>("#level button").forEach((b) => {
        if (meta.levels!.includes(b.dataset.level ?? "")) return;
        b.disabled = true;
        b.title = "Not included in this export (re-export with --symbols)";
      });
    }
  } catch (err) {
    toast(err instanceof Error ? err.message : String(err), true);
  }
  if (!source.live) {
    for (const id of ["f-changed", "o-diff", "o-diff-go"]) $<HTMLInputElement>(id).disabled = true;
  }
  app.savedPositions = await source.layout().catch(() => ({}));
  await app.load();
  bindLive(app, animator);
  app.on("view", () => animator.kick());
}

void boot();
