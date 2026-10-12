import "@fontsource-variable/bricolage-grotesque";
import "@fontsource/jetbrains-mono/400.css";
import "./dashboard.css";
import "./dashboard-polish.css";

type Usage = Record<string, number>;
interface Configuration { repository: string; source_commit: string; task: string; host: string; model: string; reasoning: string; delivery: string }
interface Check { name: string; passed: boolean; independent: boolean }
interface Arm { status: string; configuration: Configuration; checks: Check[]; usage_records: unknown[]; session_usage: unknown; elapsed_seconds: number | null; patch: string; trace: string }
interface Summary { comparable: boolean; reasons: string[]; savings: { total: number | null; fresh: number | null }; arms: Record<string, { passed: boolean; usage: Usage | null }> }
interface Run { id: string; imported_at: number; provenance: string; report: { schema_version: number; configuration: Configuration; arms: Record<string, Arm>; evidence: Record<string, boolean> }; summary: Summary }
interface Host { id: string; name: string; installed: boolean; managed: boolean; reason: string; handoff: boolean }
interface Status { project: string; root: string; branch: string | null; commit: string | null; dirty: boolean; stats: Record<string, unknown>; last_scan: string | null; index_revision: string; job: Job | null; consent: string; fresh: boolean }
interface Job { id: string; state: string; error?: string }
interface Preparation { source_commit: string; task: string; files: number; original_dirty: boolean; arms: Record<string,string>; matching_source_verified: boolean; baseline_prism_absent: boolean; isolation_verified: boolean; agent_sessions_started: number; indexing: {seconds: number; stats: Record<string,number>; llm_calls: number; llm_tokens: number}; limitations: string[] }
interface SandboxJob extends Job { preparation?: Preparation }

const el = <T extends HTMLElement = HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element ${id}`);
  return node as T;
};
const node = (tag: string, text?: string, className?: string): HTMLElement => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
let current: Run | null = null;
let status: Status | null = null;
let hosts: Host[] = [];
let packetText = "";
let packet: unknown = null;
let refreshTimer: number | undefined;
let activePage = "compare";
let runsGeneration = 0;
let contextBusy = false;
let sandboxTimer: number | undefined;
let statusBusy = false;
const number = (value: number | null | undefined): string => value == null ? "Unavailable" : value.toLocaleString();

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/dashboard/${path}`, {
    credentials: "same-origin", headers: body === undefined ? {} : { "Content-Type": "application/json" },
    method: body === undefined ? "GET" : "POST", body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message ?? data.error ?? `Request failed (${response.status})`);
  return data as T;
}
function notify(message: string, error = false): void {
  const box = el("notification"); box.textContent = message; box.hidden = false; box.classList.toggle("error", error);
  window.setTimeout(() => { if (box.textContent === message) box.hidden = true; }, 9000);
}
function download(name: string, text: string, type = "application/json"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function route(): void {
  const requested = location.hash.slice(1) || "compare";
  if (requested === "content") { el("content").focus(); return; }
  const page = ["compare", "repository", "context", "graph", "runs", "settings"].includes(requested) ? requested : "compare";
  const changed = page !== activePage;
  activePage = page;
  document.querySelectorAll<HTMLElement>("[data-view]").forEach(v => { v.hidden = v.dataset.view !== page; });
  document.querySelectorAll<HTMLAnchorElement>("[data-page]").forEach(v => {
    const selected = v.dataset.page === page; v.classList.toggle("active", selected);
    if (selected) v.setAttribute("aria-current", "page"); else v.removeAttribute("aria-current");
  });
  if (page === "graph" && !el<HTMLIFrameElement>("graph-frame").getAttribute("src")) el<HTMLIFrameElement>("graph-frame").src = "/";
  if (page === "runs") void loadRuns().catch(e => notify(String(e), true));
  if (page === "repository" || page === "graph") void syncStatus();
  if (changed) { window.scrollTo({top: 0}); el("content").focus({preventScroll: true}); }
}
function theme(): void {
  const choice = el<HTMLSelectElement>("theme").value;
  document.documentElement.dataset.theme = choice === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : choice;
  try { localStorage.setItem("prism-dashboard-theme", choice); localStorage.setItem("prism-theme", document.documentElement.dataset.theme!); } catch { /* Storage may be disabled. */ }
  el<HTMLIFrameElement>("graph-frame").contentWindow?.postMessage({type: "prism-dashboard-theme", theme: document.documentElement.dataset.theme}, location.origin);
}
function pair(label: string, value: string): DocumentFragment {
  const fragment = document.createDocumentFragment(); fragment.append(node("dt", label), node("dd", value)); return fragment;
}
function renderStatus(s: Status): void {
  status = s; el("project").textContent = s.project; el("branch").textContent = s.branch || "No Git branch";
  el("revision").textContent = `INDEX ${s.index_revision.slice(0, 12)}`;
  el("connection").textContent = "Local connection"; el("connection").classList.add("good");
  document.title = `${s.project} · PRISM workspace`;
  const stats = el("repo-stats"); stats.replaceChildren();
  for (const [label, value] of [["Indexed files", s.stats.files], ["Symbols", s.stats.symbols], ["Call edges", s.stats.call_edges], ["Parse errors", s.stats.parse_errors]]) {
    const card = node("article", undefined, "stat-card panel"); card.append(node("span", String(label)), node("strong", typeof value === "number" ? number(value) : "Unavailable")); stats.append(card);
  }
  el("repo-details").replaceChildren(
    pair("Repository", s.root), pair("Branch", s.branch || "Unavailable"), pair("Commit", s.commit || "Not a Git checkout"),
    pair("Working tree", s.dirty ? "Local changes present; committed benchmarks must exclude them" : "Clean"),
    pair("Last scan", s.last_scan ? new Date(s.last_scan).toLocaleString() : "Not indexed"), pair("Consent", s.consent), pair("Freshness", s.fresh ? "Current" : "Source changes detected; refresh required"), pair("Index revision", s.index_revision),
  );
  const coverage = el("coverage"); coverage.replaceChildren();
  const languages = s.stats.languages;
  if (languages && typeof languages === "object") for (const [language, files] of Object.entries(languages)) {
    const row = node("div", undefined, "language-row"); row.append(node("span", language), node("strong", `${files} files`)); coverage.append(row);
  }
  else coverage.append(node("p", "Language coverage unavailable", "muted"));
  renderJob(s.job);
  if (s.job?.state === "running" && refreshTimer === undefined) pollRefresh();
}
async function syncStatus(): Promise<void> {
  if (statusBusy || document.hidden) return;
  statusBusy = true;
  try { renderStatus(await api<Status>("status")); }
  catch {
    el("connection").textContent = "Disconnected · data may be stale"; el("connection").classList.remove("good");
  } finally { statusBusy = false; }
}
function renderSandbox(job: SandboxJob | null): void {
  const box = el("sandbox-status"); box.replaceChildren();
  el<HTMLButtonElement>("prepare-sandboxes").disabled = current !== null || job?.state === "running";
  if (!job) return;
  if (job.state === "running") { box.append(node("p", "Preparing matching committed copies and building the With PRISM index…", "notice")); return; }
  if (!job.preparation) { box.append(node("p", `Preparation ${job.state}: ${job.error || "details unavailable"}`, "notice")); return; }
  const preparation = job.preparation;
  const details = node("dl");
  details.append(pair("Pinned source", preparation.source_commit), pair("Prepared task", preparation.task), pair("Without PRISM", preparation.arms.without), pair("With PRISM", preparation.arms.with), pair("Source match", preparation.matching_source_verified ? "Verified during extraction" : "Not verified"), pair("Baseline context", preparation.baseline_prism_absent ? "No PRISM index" : "Not verified"), pair("Index cost", `${preparation.indexing.seconds.toFixed(2)} seconds · ${preparation.indexing.stats.files} files · ${preparation.indexing.stats.symbols} symbols · ${preparation.indexing.stats.parse_errors} parse errors`), pair("Index LLM usage", `${preparation.indexing.llm_calls} calls · ${preparation.indexing.llm_tokens} tokens`), pair("Agent runs", `${preparation.agent_sessions_started} — no benchmark scores produced`));
  box.append(details, node("p", preparation.original_dirty ? "This preparation excludes your uncommitted changes." : "The committed source was used.", "muted"), node("p", preparation.limitations.join(" "), "notice"));
}
function pollSandboxes(): void {
  if (sandboxTimer !== undefined) clearTimeout(sandboxTimer);
  sandboxTimer = window.setTimeout(() => { void api<SandboxJob | null>("sandboxes").then(job => {
    sandboxTimer = undefined; renderSandbox(job);
    if (job?.state === "running") pollSandboxes();
  }).catch(error => { sandboxTimer = undefined; notify(`Preparation status unavailable: ${error}`, true); }); }, 1500);
}
function renderJob(job: Job | null): void {
  const box = el("index-job"); box.hidden = !job;
  if (job) box.textContent = `Index refresh ${job.state}${job.error ? `: ${job.error}` : ""}`;
  el<HTMLButtonElement>("refresh-index").disabled = job?.state === "running";
}
function hostState(): void {
  const chosen = hosts.find(h => h.id === el<HTMLSelectElement>("host").value);
  el("host-state").textContent = chosen ? `${chosen.name}: ${chosen.installed ? "Executable detected" : "Executable not detected on PATH"}` : "Host capabilities unavailable";
  el("runner-limit").textContent = chosen?.reason || "No validated execution adapter is available.";
  el<HTMLButtonElement>("start-run").disabled = true;
  el<HTMLButtonElement>("prepare-sandboxes").disabled = current !== null || sandboxTimer !== undefined;
  el<HTMLButtonElement>("start-run").title = current ? "Recorded runs cannot be dispatched again; create a new task setup" : "Live execution adapter is not implemented yet";
}
function renderHosts(): void {
  const cards = el("host-cards"); cards.replaceChildren();
  for (const host of hosts) {
    const card = node("article", undefined, "panel host-card");
    card.append(node("div", host.id === "codex" ? "⌘" : host.id === "claude" ? "✳" : "↗", "host-icon"), node("h2", host.name), node("span", host.installed ? "Executable detected" : "Setup required", "pill"), node("p", host.reason, "muted"));
    const details = node("dl"); details.append(pair("Context handoff", "Available"), pair("Managed run", host.managed ? "Validated" : "Not validated"), pair("Provider usage", "Not verified")); card.append(details); cards.append(card);
  }
  hostState();
}
function emptyArm(name: string): HTMLElement {
  const empty = node("div", undefined, "empty"); empty.append(node("span", name === "with" ? "△" : "↗", "empty-icon"), node("h3", "No measured run yet"), node("p", name === "with" ? "Delivered context, necessary fallbacks and changes will appear here." : "Normal navigation, source reads and changes will appear here.")); return empty;
}
function renderArm(name: string, tab = "overview"): void {
  const panel = el(name); const body = panel.querySelector<HTMLElement>(".arm-body")!; body.replaceChildren();
  panel.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach(b => {
    const selected = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(selected)); b.tabIndex = selected ? 0 : -1;
    b.id = `${name}-tab-${b.dataset.tab}`; b.setAttribute("aria-controls", `${name}-tabpanel`);
  });
  body.id = `${name}-tabpanel`; body.tabIndex = 0; body.setAttribute("aria-labelledby", `${name}-tab-${tab}`);
  if (!current) { panel.querySelector(".arm-state")!.textContent = "Awaiting evidence"; body.append(emptyArm(name)); return; }
  const arm = current.report.arms[name]; const summary = current.summary.arms[name];
  panel.querySelector(".arm-state")!.textContent = arm.status;
  if (tab === "overview") {
    const dl = node("dl", undefined, "arm-stats");
    dl.append(pair("Independent checks", summary.passed ? "Passed" : "Not passed"), pair("Total tokens", number(summary.usage?.total_tokens)), pair("Uncached + output", number(summary.usage?.fresh_tokens)), pair("Elapsed", arm.elapsed_seconds == null ? "Unavailable" : `${arm.elapsed_seconds.toFixed(1)} seconds`));
    body.append(dl, node("p", "Token estimates are not substituted for actual usage. Missing measurements remain unavailable.", "muted"));
  } else if (tab === "checks") {
    for (const check of arm.checks) {
      const row = node("div", undefined, "check-row"); row.append(node("span", check.passed ? "✓" : "×", check.passed ? "good-text" : "bad-text"), node("span", check.name), node("span", check.independent ? "Independent" : "Agent check", "pill")); body.append(row);
    }
    if (!arm.checks.length) body.append(node("p", "Independent checks unavailable", "muted"));
  } else {
    body.append(node("pre", (tab === "trace" ? arm.trace : arm.patch) || `No ${tab === "trace" ? "trace" : "patch"} supplied`, "source"));
    if (tab === "code" && arm.patch) {
      const button = node("button", "Export this patch", "quiet-button") as HTMLButtonElement;
      button.addEventListener("click", () => download(`prism-${name}-${current!.id.slice(0, 8)}.patch`, arm.patch, "text/plain")); body.append(button);
    }
  }
}
function metrics(): void {
  const box = el("metrics"); box.replaceChildren();
  const table = node("table"); const header = node("tr"); header.append(node("th", "Metric"), node("th", "Without PRISM"), node("th", "With PRISM"));
  const thead = node("thead"); thead.append(header); const tbody = node("tbody");
  for (const [label, key] of [["Input", "input_tokens"], ["Cached input", "cached_input_tokens"], ["Uncached input", "uncached_input_tokens"], ["Output (includes reasoning)", "output_tokens"], ["Total", "total_tokens"], ["Uncached input + output", "fresh_tokens"]]) {
    const tr = node("tr"); tr.append(node("th", label), node("td", current ? number(current.summary.arms.without.usage?.[key]) : "—"), node("td", current ? number(current.summary.arms.with.usage?.[key]) : "—")); tbody.append(tr);
  }
  table.append(thead, tbody); const scroll = node("div", undefined, "table-scroll"); scroll.append(table); box.append(scroll);
  el("comparison-status").textContent = current ? (current.summary.comparable ? "Checks & totals reconcile" : "Not comparable") : "No run selected";
  if (current) {
    const note = node("div", undefined, "notice");
    if (!current.summary.comparable) {
      note.append(node("strong", "Equivalent-success savings unavailable"));
      const details = node("details"); details.append(node("summary", `Review ${current.summary.reasons.length} validation issues`));
      const list = node("ul"); current.summary.reasons.forEach(reason => list.append(node("li", reason))); details.append(list); note.append(details);
    }
    else {
      const raw = current.summary.savings.total; const fresh = current.summary.savings.fresh;
      note.append(node("strong", raw === null ? "Raw savings undefined (zero baseline)" : `${Math.abs(raw).toFixed(1)}% ${raw >= 0 ? "fewer" : "more"} total tokens`), node("p", fresh == null ? "Fresh-token change unavailable" : `Uncached input + output: ${fresh.toFixed(1)}% saving. These are token changes, not verified billing savings.`));
    }
    box.append(note, node("p", "Imported evidence is reported as supplied by its author. This dashboard checks consistency; it has not independently authenticated provider records. One pair describes one task only.", "muted"));
  }
}
function showRun(run: Run): void {
  current = run; const spec = run.report.configuration;
  el<HTMLTextAreaElement>("task").value = spec.task; el<HTMLInputElement>("model").value = spec.model;
  selectRecordedOption("host", spec.host);
  selectRecordedOption("delivery", spec.delivery);
  for (const id of ["host", "model", "delivery", "task"]) el<HTMLInputElement>(id).disabled = true;
  el("new-comparison").hidden = false;
  document.querySelector(".configuration")!.classList.add("recorded-configuration");
  const banner = el("run-banner"); banner.hidden = false; banner.textContent = `RECORDED / ${spec.repository} / ${spec.source_commit.slice(0, 12)} / ${spec.host} · ${spec.model} / ${spec.reasoning} / ${run.provenance}`;
  renderArm("without"); renderArm("with"); metrics(); hostState(); el<HTMLButtonElement>("export-report").disabled = false;
  location.hash = "compare";
}
function selectRecordedOption(id: string, value: string): void {
  const select = el<HTMLSelectElement>(id);
  if (!Array.from(select.options).some(option => option.value === value)) {
    const option = new Option(`${value} (recorded)`, value); option.dataset.recorded = "true"; select.add(option);
  }
  select.value = value;
}
function newComparison(): void {
  current = null;
  el("run-banner").hidden = true; el("new-comparison").hidden = true;
  document.querySelector(".configuration")!.classList.remove("recorded-configuration");
  for (const id of ["host", "model", "delivery", "task"]) el<HTMLInputElement>(id).disabled = false;
  for (const id of ["host", "delivery"]) {
    const select = el<HTMLSelectElement>(id); const selected = select.value;
    select.querySelectorAll("option[data-recorded]").forEach(option => option.remove());
    if (Array.from(select.options).some(option => option.value === selected)) select.value = selected;
  }
  el<HTMLButtonElement>("export-report").disabled = true;
  el<HTMLInputElement>("model").value = "";
  renderArm("without"); renderArm("with"); metrics(); hostState(); el("task").focus();
}
async function loadRuns(): Promise<void> {
  const generation = ++runsGeneration;
  el("runs-list").replaceChildren(node("p", "Loading recorded runs…", "loading-line"));
  const runs = await api<Array<Omit<Run, "report"> & { configuration: Configuration }>>("runs").catch(error => {
    if (generation === runsGeneration) {
      const message = node("article", undefined, "panel empty"); const retry = node("button", "Retry loading runs", "quiet-button") as HTMLButtonElement;
      retry.addEventListener("click", () => { void loadRuns().catch(e => notify(String(e), true)); });
      message.append(node("h3", "Could not load runs"), node("p", "Check your local server connection, then retry."), retry); el("runs-list").replaceChildren(message);
    }
    throw error;
  });
  if (generation !== runsGeneration) return;
  const list = el("runs-list"); list.replaceChildren();
  if (!runs.length) { const empty = node("div", undefined, "panel empty"); empty.append(node("span", "◷", "empty-icon"), node("h3", "No recorded comparisons"), node("p", "Import an evidence report to review both solutions, provider usage and independent checks.")); list.append(empty); }
  for (const run of runs) {
    const row = node("button", undefined, "panel run-row") as HTMLButtonElement;
    const title = node("div"); title.append(node("strong", run.configuration.task), node("p", `${run.configuration.repository} · ${run.configuration.host} / ${run.configuration.model}`, "muted"));
    row.append(title, node("span", run.summary.comparable ? "Checks reconcile" : "Incomplete evidence", "pill"), node("time", new Date(run.imported_at * 1000).toLocaleString()));
    row.addEventListener("click", () => { void api<Run>(`runs/${run.id}`).then(showRun).catch(e => notify(String(e), true)); }); list.append(row);
  }
}
function template(): object {
  const configuration: Configuration = { repository: status?.project || "repository-name", source_commit: status?.commit || "FULL_GIT_COMMIT_REQUIRED", task: el<HTMLTextAreaElement>("task").value || "Describe the single task", host: el<HTMLSelectElement>("host").value, model: el<HTMLInputElement>("model").value || "exact-model", reasoning: "record-effective-setting", delivery: el<HTMLSelectElement>("delivery").value };
  const arm = (): Arm => ({ status: "interrupted", configuration: { ...configuration }, checks: [], usage_records: [], session_usage: null, elapsed_seconds: null, patch: "", trace: "" });
  return { schema_version: 1, configuration, evidence: { isolation_verified: false, baseline_prism_absent: false, matching_source_verified: false, hook_context_delivered: false }, arms: { without: arm(), with: arm() } };
}
async function retrieve(event: SubmitEvent): Promise<void> {
  event.preventDefault(); if (contextBusy) return; contextBusy = true;
  const button = el<HTMLButtonElement>("retrieve"); button.disabled = true; button.textContent = "Retrieving…";
  const query = el<HTMLTextAreaElement>("context-query").value;
  const controls = ["context-query", "budget", "context-mode"].map(id => el<HTMLInputElement>(id));
  controls.forEach(control => { control.disabled = true; });
  el("context-output").setAttribute("aria-busy", "true");
  try {
    const budgetInput = el<HTMLInputElement>("budget").value;
    const response = await api<{ packet: Record<string, unknown>; text: string; index_revision: string; last_scan: string | null }>("context", { query, budget: budgetInput === "" ? null : Number(budgetInput), mode: el<HTMLSelectElement>("context-mode").value });
    packet = response.packet; packetText = response.text;
    const output = el("context-output"); const title = node("div", undefined, "section-title"); const actions = node("div", undefined, "actions");
    const copy = node("button", "Copy packet", "quiet-button") as HTMLButtonElement;
    copy.addEventListener("click", () => { void navigator.clipboard.writeText(packetText).then(() => notify("Exact context packet copied")).catch(() => notify("Clipboard unavailable; use Download", true)); });
    const exportButton = node("button", "Download", "quiet-button") as HTMLButtonElement; exportButton.addEventListener("click", () => download("prism-context.txt", packetText, "text/plain"));
    const structured = node("button", "Structured JSON", "quiet-button") as HTMLButtonElement;
    structured.addEventListener("click", () => { const source = output.querySelector("pre")!; source.textContent = structured.textContent === "Structured JSON" ? JSON.stringify(packet, null, 2) : packetText; structured.textContent = structured.textContent === "Structured JSON" ? "Readable" : "Structured JSON"; });
    actions.append(copy, exportButton, structured); title.append(node("h2", "Exact context packet"), actions);
    const budget = response.packet.budget as { used_est?: number } | undefined;
    output.replaceChildren(title, node("p", query, "context-request"), node("p", `Confidence: ${response.packet.confidence ?? "unavailable"} · Sufficient: ${response.packet.sufficient ?? "unavailable"} · Estimated context tokens: ${number(budget?.used_est)}`, "muted"), node("p", `Packet index revision: ${response.index_revision.slice(0,12)} · ${response.last_scan ? new Date(response.last_scan).toLocaleString() : "Unavailable"}`, "muted"), node("pre", packetText, "source"));
    void syncStatus();
  } catch (e) { notify(e instanceof Error ? e.message : String(e), true); }
  finally { contextBusy = false; button.disabled = false; button.textContent = "Retrieve context"; controls.forEach(control => { control.disabled = false; }); el("context-output").removeAttribute("aria-busy"); }
}
async function refresh(): Promise<void> {
  el<HTMLButtonElement>("refresh-index").disabled = true;
  const job = await api<Job>("refresh", {}); renderJob(job);
  pollRefresh();
}
function pollRefresh(): void {
  if (refreshTimer !== undefined) clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => { void api<Job>("job").then(async j => {
    renderJob(j);
    if (j.state !== "running") { refreshTimer = undefined; renderStatus(await api<Status>("status")); notify(j.state === "completed" ? "Index refreshed" : `Refresh failed: ${j.error}`, j.state !== "completed"); }
    else pollRefresh();
  }).catch(e => { refreshTimer = undefined; el<HTMLButtonElement>("refresh-index").disabled = false; notify(`Refresh status unavailable: ${e}. Reload to reconnect.`, true); }); }, 1500);
}
function bind(): void {
  window.addEventListener("hashchange", route);
  document.querySelector<HTMLAnchorElement>(".skip")!.addEventListener("click", event => { event.preventDefault(); el("content").focus(); });
  el("theme").addEventListener("change", theme); matchMedia("(prefers-color-scheme: light)").addEventListener("change", theme);
  try { const saved = localStorage.getItem("prism-dashboard-theme"); el<HTMLSelectElement>("theme").value = saved && ["system", "light", "dark"].includes(saved) ? saved : "system"; } catch { /* Optional persistence. */ }
  theme(); route();
  el("host").addEventListener("change", () => { el<HTMLInputElement>("model").value = ""; hostState(); });
  el("prepare-context").addEventListener("click", () => {
    if (contextBusy) { notify("A context request is still running. Wait for it to finish before previewing another task."); return; }
    el<HTMLTextAreaElement>("context-query").value = el<HTMLTextAreaElement>("task").value; location.hash = "context";
  });
  el("context-form").addEventListener("submit", e => { void retrieve(e as SubmitEvent); });
  el("refresh-index").addEventListener("click", () => { void refresh().catch(e => { el<HTMLButtonElement>("refresh-index").disabled = false; notify(String(e), true); }); });
  el("new-comparison").addEventListener("click", newComparison);
  el("prepare-sandboxes").addEventListener("click", () => {
    const button = el<HTMLButtonElement>("prepare-sandboxes"); button.disabled = true;
    void api<SandboxJob>("sandboxes", {task: el<HTMLTextAreaElement>("task").value}).then(job => { renderSandbox(job); if (job.state === "running") pollSandboxes(); }).catch(error => {button.disabled = false; notify(String(error),true);});
  });
  el("heading-import").addEventListener("click", () => el<HTMLInputElement>("report-file").click());
  el("import-report").addEventListener("click", () => el<HTMLInputElement>("report-file").click());
  el("runs-import").addEventListener("click", () => el<HTMLInputElement>("report-file").click());
  el("report-file").addEventListener("change", async () => {
    const input = el<HTMLInputElement>("report-file"); const file = input.files?.[0]; if (!file) return;
    try { if (file.size > 4 * 1024 * 1024) throw new Error("Report exceeds 4 MB"); const run = await api<Run>("runs", JSON.parse(await file.text())); showRun(run); notify("Evidence imported; consistency checks completed"); }
    catch (e) { notify(e instanceof Error ? e.message : String(e), true); }
    finally { input.value = ""; }
  });
  el("schema-download").addEventListener("click", () => download("prism-report-template.json", JSON.stringify(template(), null, 2)));
  el("export-report").addEventListener("click", () => { if (current) download(`prism-report-${current.id.slice(0, 8)}.json`, JSON.stringify({...current.report, dashboard_metadata: {id: current.id, provenance: current.provenance, imported_at: current.imported_at, summary: current.summary}}, null, 2)); });
  for (const name of ["without", "with"]) {
    const buttons = Array.from(el(name).querySelectorAll<HTMLButtonElement>("[data-tab]"));
    for (const button of buttons) {
      button.addEventListener("click", () => renderArm(name, button.dataset.tab));
      button.addEventListener("keydown", e => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
        e.preventDefault(); const index = buttons.indexOf(button); const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : (index + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next].focus(); renderArm(name, buttons[next].dataset.tab);
      });
    }
    renderArm(name);
  }
  metrics();
}
bind();
window.setInterval(() => { void syncStatus(); }, 15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) void syncStatus(); });
void api<SandboxJob | null>("sandboxes").then(job => {renderSandbox(job); if (job?.state === "running") pollSandboxes();}).catch(() => { /* Existing status request explains server connection failures. */ });
void Promise.allSettled([api<Status>("status").then(renderStatus), api<Host[]>("hosts").then(data => { hosts = data; renderHosts(); })]).then(results => {
  if (results[0].status === "rejected") { el("connection").textContent = "Connection unavailable"; notify(`Could not connect: ${results[0].reason}. Open the authenticated URL printed by prism view.`, true); }
  if (results[1].status === "rejected") { el("host-state").textContent = "Host detection unavailable"; notify(`Host detection failed: ${results[1].reason}`, true); }
});
