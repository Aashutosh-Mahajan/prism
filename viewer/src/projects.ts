import { call, mk, q, say, selectedProject, setSelectedProject, type Project } from "./shared";

// The project list, the switcher in the top bar and the Projects page (add, index, remove).

interface Listing { projects: Project[]; selected: string; default: string }
let projects: Project[] = [];
let timer: number | undefined;
let refreshGeneration = 0;
let selectionGeneration = 0;
let selectionQueue: Promise<unknown> = Promise.resolve();
const watchers: Array<(list: Project[]) => void> = [];

export const allProjects = (): Project[] => projects;
export function onProjects(listener: (list: Project[]) => void): void { watchers.push(listener); }

const STATE: Record<string, string> = {
  ready: "Ready", needs_index: "Needs indexing", cloning: "Downloading…", indexing: "Indexing…", failed: "Failed", missing: "Folder missing",
};

function switcher(): void {
  const select = q<HTMLSelectElement>("project-switch");
  select.replaceChildren(...projects.map(p => { const option = document.createElement("option"); option.value = p.id; option.textContent = p.name; option.disabled = p.state !== "ready"; return option; }));
  const chosen = selectedProject();
  if (chosen && projects.some(p => p.id === chosen)) select.value = chosen;
}
function card(project: Project): HTMLElement {
  const box = mk("article", undefined, `panel project-card${project.id === selectedProject() ? " current" : ""}`);
  const head = mk("div", undefined, "project-head");
  head.append(mk("h2", project.name), mk("span", STATE[project.state] ?? project.state, `pill ${project.state === "ready" ? "good" : ""}`));
  const facts = mk("p", undefined, "muted");
  facts.textContent = project.source === "git" ? `${project.url ?? "git"} (downloaded copy)` : project.root;
  box.append(head, facts);
  if (project.files != null) box.append(mk("p", `${project.files.toLocaleString()} files · ${(project.symbols ?? 0).toLocaleString()} symbols`, "muted"));
  if (project.error) box.append(mk("p", project.error, "live-note warn"));
  const actions = mk("div", undefined, "live-actions");
  const use = mk("button", project.id === selectedProject() ? "In use" : "Use this project", "quiet-button") as HTMLButtonElement;
  use.disabled = project.id === selectedProject() || project.state !== "ready";
  use.addEventListener("click", () => { void choose(project.id).catch(e => say(String(e), true)); });
  actions.append(use);
  if (project.state === "needs_index" || project.state === "failed" || (project.state === "missing" && project.source === "git")) {
    const retryDownload = project.source === "git" && project.state === "missing";
    const index = mk("button", retryDownload ? "Retry download" : "Index this project", "primary-button") as HTMLButtonElement;
    let armed = false;
    index.addEventListener("click", () => {
      if (!armed) {  // two steps: first show exactly what will change, then do it
        armed = true; index.textContent = retryDownload ? "Confirm: download and index" : "Confirm: create .aicontext here";
        box.append(mk("p", retryDownload ? `Downloads ${project.url} into ${project.root} and builds its PRISM index.` : `Indexing creates a .aicontext folder inside ${project.root} and adds it to that folder's .gitignore. Your code is not changed.`, "live-note"));
        return;
      }
      void call("projects/index", { id: project.id }, null).then(() => refresh()).catch(e => say(String(e), true));
    });
    actions.append(index);
  }
  if (!project.default) {
    const remove = mk("button", "Remove from list", "quiet-button") as HTMLButtonElement;
    remove.addEventListener("click", () => { void call("projects/remove", { id: project.id }, null).then(async () => { if (selectedProject() === project.id) await choose(projects.find(p => p.default)!.id); await refresh(); }).catch(e => say(String(e), true)); });
    actions.append(remove);
  }
  box.append(actions);
  return box;
}
function render(): void {
  switcher();
  const list = q("project-list"); list.replaceChildren(...projects.map(card));
  watchers.forEach(watcher => watcher(projects));
}
export async function refresh(): Promise<void> {
  const generation = ++refreshGeneration;
  const listing = await call<Listing>("projects", undefined, null);
  if (generation !== refreshGeneration) return;
  projects = listing.projects;
  if (selectedProject() === null) setSelectedProject(listing.selected, false);
  if (selectedProject() && !projects.some(p => p.id === selectedProject())) setSelectedProject(listing.default);
  render();
  if (timer !== undefined) clearTimeout(timer);
  if (projects.some(p => p.state === "cloning" || p.state === "indexing")) timer = window.setTimeout(() => { void refresh().catch(e => say(`Project status unavailable: ${e}`, true)); }, 2000);
}
export async function choose(id: string): Promise<void> {
  const generation = ++selectionGeneration;
  // Keep the server cookie in selection order even when the user switches quickly.
  const request = selectionQueue.catch(() => undefined).then(() => call("projects/select", { id }, null));
  selectionQueue = request;
  await request;
  if (generation !== selectionGeneration) return;
  setSelectedProject(id);
  const url = new URL(location.href); url.searchParams.set("project", id); history.replaceState(null, "", url);
  render();
}
async function add(body: Record<string, string>, input: HTMLInputElement): Promise<void> {
  try {
    const project = await call<Project>("projects", body, null);
    input.value = "";
    say(project.state === "cloning" ? "Downloading the repository. It will be indexed automatically." : "Project added. Index it to use it.");
    await refresh();
  } catch (error) { say(error instanceof Error ? error.message : String(error), true); }
}
export async function initProjects(): Promise<void> {
  q("project-switch").addEventListener("change", () => { void choose(q<HTMLSelectElement>("project-switch").value).catch(e => say(String(e), true)); });
  const path = q<HTMLInputElement>("project-path"); const url = q<HTMLInputElement>("project-url");
  q("project-add-path").addEventListener("click", () => { void add({ path: path.value }, path); });
  q("project-add-url").addEventListener("click", () => { void add({ git_url: url.value }, url); });
  await refresh().catch(e => say(`Could not load projects: ${e}`, true));
  const requested = new URLSearchParams(location.search).get("project");
  if (requested && projects.some(project => project.id === requested && project.state === "ready")) await choose(requested).catch(e => say(String(e), true));
}
