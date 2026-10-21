import "./live-compare.css";
import { allProjects, onProjects } from "./projects";
import { call, change, fmt, mk, money, onProjectChange, q, say, secs, selectedProject } from "./shared";

// Live paired runs. Each panel runs one project and one agent twice at once (without and with PRISM) and
// streams messages, terminal commands and token counters. Several panels show several projects together.

interface LiveEvent { kind: "info" | "text" | "tool" | "result" | "terminal_start" | "terminal_end"; text?: string; name?: string; ok?: boolean; id?: string; command?: string; output?: string; t: number }
type Usage = { input_tokens: number; cache_creation_tokens: number; cache_read_tokens: number; output_tokens: number; input_total: number; total_tokens: number };
interface Check { ran: boolean; passed: boolean; exit_code: number | null; output: string; seconds: number }
interface ArmState {
  state: string; events: LiveEvent[]; event_count: number; usage: Usage | null; usage_final: boolean; turns: number | null;
  started: number | null; finished: number | null; duration_seconds: number | null; cost_usd: number | null; commands_run: number;
  final_text: string; error: string | null; patch: string; files_changed: string[]; lines_added: number; lines_removed: number; check: Check | null;
}
interface Verdict {
  quality: string; token_saving_pct: number | null; input_saving_pct: number | null; output_saving_pct: number | null; cost_saving_pct: number | null;
  time_saving_pct: number | null; commands_saving_pct: number | null; identical_patch: boolean;
}
type Arms = Record<"without" | "with", ArmState>;
interface LiveRun {
  id: string; state: string; agent: string; agent_name: string; manual: boolean; task: string; check_command: string; error: string | null;
  preparation: { arms: Record<"without" | "with", string> } | null; arms: Arms; verdict: Verdict | null; started: number; finished: number | null;
}
interface AgentInfo { id: string; name: string; mode: "live" | "manual"; found: boolean; version: string | null; logged_in: boolean | null }
interface Row {
  id: string; task: string; agent: string; agent_name: string; state: string; started: number; verdict: Verdict | null;
  without: { usage: Usage | null; cost_usd: number | null; duration_seconds: number | null; commands_run: number };
  with: { usage: Usage | null; cost_usd: number | null; duration_seconds: number | null; commands_run: number };
}

const ARMS = ["without", "with"] as const;
const ACTIVE = ["preparing", "running", "checking", "awaiting_manual"];
const TITLES = { without: "Without PRISM", with: "With PRISM" } as const;
let agents: AgentInfo[] = [];

// --- the feed: messages and terminal commands ------------------------------------------------

class Feed {
  private blocks = new Map<string, { status: HTMLElement; out: HTMLElement }>();
  constructor(readonly el: HTMLElement, private readonly mode: "activity" | "terminal") {}
  reset(): void { this.el.replaceChildren(); this.blocks.clear(); }
  add(event: LiveEvent): void {
    const stick = this.el.scrollTop + this.el.clientHeight >= this.el.scrollHeight - 30;
    if (event.kind === "terminal_start") {
      const block = mk("div", undefined, "term-block"); const line = mk("div", undefined, "term-cmd");
      const status = mk("span", "running…", "term-status"); const out = mk("pre", "", "term-out"); out.hidden = true;
      line.append(mk("b", "$ "), mk("span", event.command ?? ""), status); block.append(line, out); this.el.append(block);
      this.blocks.set(event.id ?? "", { status, out });
    } else if (event.kind === "terminal_end") {
      const block = this.blocks.get(event.id ?? "");
      if (block) { block.status.textContent = event.ok ? "✓ done" : "✗ failed"; block.status.className = `term-status ${event.ok ? "ok" : "bad"}`; block.out.textContent = event.output ?? ""; block.out.hidden = !event.output; }
    } else if (this.mode === "activity") {
      if (event.kind === "tool") { const row = mk("div", undefined, "ev-tool"); row.append(mk("b", `▸ ${event.name}`), mk("span", ` ${event.text ?? ""}`)); this.el.append(row); }
      else if (event.kind === "result") this.el.append(mk("div", `${event.ok ? "✓" : "✗"} ${event.text ?? ""}`, `ev-result${event.ok ? "" : " bad"}`));
      else this.el.append(mk("div", event.text ?? "", event.kind === "info" ? "ev-info" : "ev-text"));
    }
    if (stick) this.el.scrollTop = this.el.scrollHeight;
  }
}

// --- result pieces used by the live panels and the Compare history ---------------------------

function metricsTable(run: { arms: Arms; check_command: string; manual?: boolean }, v: Verdict): HTMLElement {
  const a = run.arms.without; const b = run.arms.with;
  const table = mk("table", undefined, "live-table"); const head = mk("tr");
  head.append(...["Measure", "Without PRISM", "With PRISM", "PRISM used"].map(t => mk("th", t))); table.append(head);
  const row = (label: string, x: string, y: string, diff = "", pct: number | null = null): void => {
    const r = mk("tr"); r.append(mk("td", label), mk("td", x), mk("td", y), mk("td", diff, pct == null ? "" : pct >= 0 ? "good" : "bad")); table.append(r);
  };
  row("Total tokens", fmt(a.usage?.total_tokens), fmt(b.usage?.total_tokens), change(v.token_saving_pct), v.token_saving_pct);
  row("Input tokens (all)", fmt(a.usage?.input_total), fmt(b.usage?.input_total), change(v.input_saving_pct), v.input_saving_pct);
  row("  of which cached", fmt(a.usage?.cache_read_tokens), fmt(b.usage?.cache_read_tokens));
  row("Output tokens", fmt(a.usage?.output_tokens), fmt(b.usage?.output_tokens), change(v.output_saving_pct), v.output_saving_pct);
  row("Cost reported by the agent", money(a.cost_usd), money(b.cost_usd), change(v.cost_saving_pct), v.cost_saving_pct);
  row("Time", secs(a.duration_seconds), secs(b.duration_seconds), change(v.time_saving_pct), v.time_saving_pct);
  row("Terminal commands run", fmt(a.commands_run), fmt(b.commands_run), change(v.commands_saving_pct), v.commands_saving_pct);
  row("Agent turns", fmt(a.turns), fmt(b.turns));
  row("Lines changed", `+${a.lines_added} −${a.lines_removed}`, `+${b.lines_added} −${b.lines_removed}`, v.identical_patch ? "identical changes" : "different changes");
  if (run.check_command) row("Check passed", a.check?.passed ? "yes" : "NO", b.check?.passed ? "yes" : "NO", "", a.check?.passed && b.check?.passed ? 1 : -1);
  return table;
}
function verdictBox(box: HTMLElement, run: { arms: Arms; check_command: string; verdict: Verdict | null; state: string; manual?: boolean }): void {
  box.replaceChildren();
  if (!run.verdict || ACTIVE.includes(run.state)) { box.hidden = true; return; }
  box.hidden = false; const v = run.verdict;
  const saving = v.token_saving_pct == null ? "Tokens could not be measured for this run." : `PRISM used ${change(v.token_saving_pct)} tokens${v.time_saving_pct == null ? "" : ` and ${change(v.time_saving_pct)} time`}.`;
  const text: Record<string, [string, string]> = {
    same: ["Same quality, fewer resources", `The independent check passed in both runs. ${saving}`],
    degraded: ["Quality dropped with PRISM", `The check passed without PRISM but failed with it. ${saving} A saving does not count when the result is worse.`],
    better: ["PRISM passed where the baseline failed", `${saving} One run is one example, not proof.`],
    both_failed: ["Both solutions failed the check", "Neither result is correct, so no saving is meaningful."],
    unverified: ["Quality not verified", `No check command was given, so nothing proves the output is still correct. ${saving} Add a test command to prove quality.`],
    incomplete: ["A run did not finish", "No comparison is shown because at least one agent failed or was stopped."],
  };
  const [title, body] = text[v.quality] ?? ["Result", ""];
  box.className = `live-verdict ${v.quality}`;
  const parts: HTMLElement[] = [mk("strong", title), mk("p", body)];
  if (v.quality !== "incomplete") parts.push(metricsTable(run, v), mk("p", "One paired run is one example. It shows what happened on this task, not a typical saving.", "muted"));
  box.append(...parts);
}
function armDetails(arm: ArmState): HTMLElement[] {
  const out: HTMLElement[] = [];
  if (arm.error) out.push(mk("p", `Problem: ${arm.error}`, "live-note warn"));
  const detail = (title: string, text: string): void => { if (!text) return; const d = mk("details"); d.append(mk("summary", title), mk("pre", text)); out.push(d); };
  detail("Final answer", arm.final_text);
  detail(`Code changes (${arm.files_changed.length} file${arm.files_changed.length === 1 ? "" : "s"}, +${arm.lines_added} −${arm.lines_removed})`, arm.patch);
  if (arm.check) detail(`Check: ${arm.check.passed ? "passed" : "FAILED"}`, arm.check.output);
  return out;
}

// --- one live panel --------------------------------------------------------------------------

class Panel {
  readonly el = mk("section", undefined, "panel live-panel");
  private projectId: string; private agent = "claude"; private run: LiveRun | null = null; private timer: number | undefined;
  private offsets = { without: 0, with: 0 };
  private feeds = {} as Record<"without" | "with", { activity: Feed; terminal: Feed }>;
  private ui = {} as Record<string, HTMLElement>;

  constructor(projectId: string, private readonly changed: () => void) { this.projectId = projectId; this.build(); void this.load(); }

  private field<T extends HTMLElement>(tag: string, cls = "", text?: string): T { return mk(tag, text, cls) as T; }
  private build(): void {
    const ui = this.ui;
    const bar = mk("div", undefined, "live-bar");
    ui.project = this.field("select"); ui.agent = this.field("select");
    (ui.project as HTMLSelectElement).addEventListener("change", () => { this.stopPolling(); this.projectId = (ui.project as HTMLSelectElement).value; this.reset(); void this.load(); this.changed(); });
    (ui.agent as HTMLSelectElement).addEventListener("change", () => { this.agent = (ui.agent as HTMLSelectElement).value; this.agentNote(); this.changed(); });
    const label = (text: string, input: HTMLElement): HTMLElement => { const l = mk("label", undefined, "live-field"); l.append(mk("span", text), input); return l; };
    bar.append(label("Project", ui.project), label("Coding agent", ui.agent));
    ui.task = this.field("textarea"); (ui.task as HTMLTextAreaElement).rows = 3; (ui.task as HTMLTextAreaElement).placeholder = "What should the agent change? For example: Add input validation to the signup form";
    ui.check = this.field("input"); (ui.check as HTMLInputElement).placeholder = "for example: python -m pytest -q";
    ui.model = this.field("input"); (ui.model as HTMLInputElement).placeholder = "agent default";
    ui.turns = this.field("input"); (ui.turns as HTMLInputElement).type = "number"; (ui.turns as HTMLInputElement).value = "30";
    const options = mk("details", undefined, "live-options"); const grid = mk("div", undefined, "live-grid2");
    grid.append(label("Model (optional)", ui.model), label("Max turns", ui.turns)); options.append(mk("summary", "More options"), grid);
    ui.agentNote = mk("p", undefined, "live-note");
    ui.start = this.field("button", "primary-button", "Start live comparison"); (ui.start as HTMLButtonElement).type = "button";
    ui.stop = this.field("button", "quiet-button", "Stop both runs"); (ui.stop as HTMLButtonElement).type = "button"; ui.stop.hidden = true;
    (ui.start as HTMLButtonElement).addEventListener("click", () => { void this.start(); });
    (ui.stop as HTMLButtonElement).addEventListener("click", () => { void call("live/cancel", {}, this.projectId).catch(e => say(String(e), true)); });
    const actions = mk("div", undefined, "live-actions"); actions.append(ui.start, ui.stop);
    const form = mk("div", undefined, "live-form");
    form.append(bar, label("Coding task", ui.task), label("Check command (proves the result is still correct)", ui.check), options, ui.agentNote, actions);
    ui.results = mk("div"); ui.results.hidden = true;
    ui.steps = mk("div", undefined, "live-steps"); ui.status = mk("p", undefined, "live-note"); ui.manual = mk("div", undefined, "live-manual"); ui.manual.hidden = true;
    const grid2 = mk("div", undefined, "live-arms");
    for (const arm of ARMS) grid2.append(this.armCard(arm));
    ui.verdict = mk("div", undefined, "live-verdict"); ui.verdict.hidden = true;
    ui.results.append(ui.steps, ui.status, ui.manual, grid2, ui.verdict);
    this.el.append(form, ui.results);
    this.fillSelects();
  }
  private armCard(arm: "without" | "with"): HTMLElement {
    const card = mk("article", undefined, `live-arm ${arm}`); const ui = this.ui;
    const head = mk("header"); ui[`${arm}-state`] = mk("span", "waiting", "pill"); ui[`${arm}-time`] = mk("span", "", "live-time");
    head.append(mk("h3", TITLES[arm]), ui[`${arm}-state`], ui[`${arm}-time`]);
    ui[`${arm}-tokens`] = mk("div", undefined, "live-tokens");
    const tabs = mk("div", undefined, "live-tabs"); const activity = mk("button", "Activity", "tab on") as HTMLButtonElement; const terminal = mk("button", "Terminal", "tab") as HTMLButtonElement;
    activity.type = terminal.type = "button";
    const a = mk("div", undefined, "live-feed"); const t = mk("div", undefined, "live-feed terminal-feed"); t.hidden = true;
    activity.addEventListener("click", () => { a.hidden = false; t.hidden = true; activity.classList.add("on"); terminal.classList.remove("on"); });
    terminal.addEventListener("click", () => { a.hidden = true; t.hidden = false; terminal.classList.add("on"); activity.classList.remove("on"); });
    tabs.append(activity, terminal); this.feeds[arm] = { activity: new Feed(a, "activity"), terminal: new Feed(t, "terminal") };
    ui[`${arm}-extra`] = mk("div");
    card.append(head, ui[`${arm}-tokens`], tabs, a, t, ui[`${arm}-extra`]);
    return card;
  }
  fillSelects(): void {
    const projectSelect = this.ui.project as HTMLSelectElement; const agentSelect = this.ui.agent as HTMLSelectElement;
    projectSelect.replaceChildren(...allProjects().map(p => { const o = document.createElement("option"); o.value = p.id; o.textContent = `${p.name}${p.state === "ready" ? "" : ` (${p.state.replace("_", " ")})`}`; return o; }));
    if (allProjects().some(p => p.id === this.projectId)) projectSelect.value = this.projectId;
    agentSelect.replaceChildren(...(agents.length ? agents : [{ id: "claude", name: "Claude Code", mode: "live", found: true, version: null, logged_in: null } as AgentInfo]).map(a => {
      const o = document.createElement("option"); o.value = a.id; o.textContent = `${a.name}${a.mode === "manual" ? " (manual hand-off)" : a.found ? (a.logged_in === false ? " (not logged in)" : "") : " (not installed)"}`; return o;
    }));
    agentSelect.value = this.agent; this.agentNote();
  }
  private agentNote(): void {
    const info = agents.find(a => a.id === this.agent); const note = this.ui.agentNote;
    if (!info) { note.hidden = true; return; }
    note.hidden = false; note.className = "live-note";
    if (info.mode === "manual") note.textContent = "Antigravity has no headless mode. PRISM prepares both folders; you run the task in each one, then press Done to compare. Tokens cannot be measured for this agent.";
    else if (!info.found) { note.textContent = `${info.name} is not installed on this computer, so a run cannot start.`; note.className = "live-note warn"; }
    else if (info.logged_in === false) { note.textContent = `${info.name} is installed but not logged in. Log in once, then reload. A run would fail now.`; note.className = "live-note warn"; }
    else note.textContent = `${info.name} ${info.version ?? ""} is ready. Each run spends real tokens from your plan.`;
  }
  private reset(): void {
    this.run = null; this.offsets = { without: 0, with: 0 };
    for (const arm of ARMS) { this.feeds[arm].activity.reset(); this.feeds[arm].terminal.reset(); }
    this.ui.results.hidden = true;
  }
  private stopPolling(): void { if (this.timer !== undefined) { clearTimeout(this.timer); this.timer = undefined; } }
  destroy(): void { this.stopPolling(); }
  get summary(): { project: string; run: LiveRun | null } { return { project: allProjects().find(p => p.id === this.projectId)?.name ?? "project", run: this.run }; }
  get config(): { project: string; agent: string } { return { project: this.projectId, agent: this.agent }; }
  setAgent(agent: string): void { this.agent = agent; this.fillSelects(); }

  private async load(): Promise<void> {
    try { const run = await call<LiveRun | null>(`live?without=0&with=0`, undefined, this.projectId); this.render(run, true); if (run && ACTIVE.includes(run.state)) this.poll(); }
    catch { /* The project may not be indexed yet. */ }
  }
  private poll(): void {
    this.stopPolling();
    const project = this.projectId;
    this.timer = window.setTimeout(() => {
      void call<LiveRun | null>(`live?without=${this.offsets.without}&with=${this.offsets.with}`, undefined, project).then(run => {
        this.timer = undefined; if (project !== this.projectId) return;
        this.render(run); if (run && ACTIVE.includes(run.state)) this.poll();
      }).catch(error => { this.timer = undefined; say(`Live status unavailable: ${error}`, true); });
    }, 800);
  }
  private async start(): Promise<void> {
    const task = (this.ui.task as HTMLTextAreaElement).value.trim();
    if (!task) { say("Describe one coding task first.", true); return; }
    (this.ui.start as HTMLButtonElement).disabled = true;
    try {
      const run = await call<LiveRun>("live", {
        task, agent: this.agent, check_command: (this.ui.check as HTMLInputElement).value.trim(), model: (this.ui.model as HTMLInputElement).value.trim(),
        max_turns: Number((this.ui.turns as HTMLInputElement).value || 30),
      }, this.projectId);
      this.render(run, true); this.poll();
    } catch (error) { say(error instanceof Error ? error.message : String(error), true); (this.ui.start as HTMLButtonElement).disabled = false; }
  }
  private render(run: LiveRun | null, fresh = false): void {
    this.run = run; this.ui.results.hidden = run === null; this.changed();
    if (!run) return;
    if (fresh) { this.offsets = { without: 0, with: 0 }; for (const arm of ARMS) { this.feeds[arm].activity.reset(); this.feeds[arm].terminal.reset(); } }
    const order = ["preparing", "running", "checking", "completed"]; const stopped = ["failed", "cancelled", "interrupted"].includes(run.state);
    const index = stopped ? -1 : run.state === "awaiting_manual" ? 1 : order.indexOf(run.state);
    const labels = ["1  Prepare two copies", run.manual ? "2  You run the task" : "2  Run both agents", "3  Check both results", "4  Compare"];
    this.ui.steps.replaceChildren(...labels.map((label, i) => mk("span", label, run.state === "completed" || i < index ? "done" : i === index ? "on" : "")));
    const active = ACTIVE.includes(run.state);
    (this.ui.start as HTMLButtonElement).disabled = active; this.ui.stop.hidden = !active;
    const messages: Record<string, string> = { preparing: "Copying the project twice and building PRISM's index for the With copy…", running: "Both agents are working at the same time.", checking: "Running your check command in both results…", awaiting_manual: "Waiting for you to run the task in both folders.", completed: "Finished." };
    this.ui.status.textContent = run.error ?? messages[run.state] ?? `Run ${run.state}.`; this.ui.status.className = run.error ? "live-note warn" : "live-note";
    this.manualBox(run);
    for (const arm of ARMS) {
      const state = run.arms[arm];
      for (const event of state.events) { this.feeds[arm].activity.add(event); this.feeds[arm].terminal.add(event); }
      this.offsets[arm] = state.event_count;
      this.ui[`${arm}-state`].textContent = state.state;
      const usage = state.usage;
      this.ui[`${arm}-tokens`].replaceChildren(document.createTextNode(usage ? `${fmt(usage.total_tokens)} tokens` : run.manual ? "not measurable" : "waiting…"),
        mk("small", usage ? `${state.usage_final ? "final" : "so far"} · input ${fmt(usage.input_total)} (cached ${fmt(usage.cache_read_tokens)}) · output ${fmt(usage.output_tokens)} · ${state.commands_run} command${state.commands_run === 1 ? "" : "s"}` : "Token counts appear as the agent works"));
      this.ui[`${arm}-extra`].replaceChildren(...armDetails(state));
    }
    this.tick(); verdictBox(this.ui.verdict, run);
  }
  private manualBox(run: LiveRun): void {
    const box = this.ui.manual; box.hidden = run.state !== "awaiting_manual" || !run.preparation; box.replaceChildren();
    if (box.hidden || !run.preparation) return;
    const done = mk("button", "Done: check and compare", "primary-button") as HTMLButtonElement; done.type = "button";
    done.addEventListener("click", () => { done.disabled = true; void call("live/finish", {}, this.projectId).then(() => this.poll()).catch(e => { done.disabled = false; say(String(e), true); }); });
    box.append(mk("p", "Open each folder in Antigravity and give it this exact task:", "muted"), mk("pre", run.task), mk("p", `Without PRISM: ${run.preparation.arms.without}`, "muted"), mk("p", `With PRISM: ${run.preparation.arms.with}`, "muted"), done);
  }
  tick(): void {
    if (!this.run) return;
    for (const arm of ARMS) {
      const state = this.run.arms[arm];
      const seconds = state.duration_seconds ?? (state.started && !state.finished ? Date.now() / 1000 - state.started : null);
      this.ui[`${arm}-time`].textContent = seconds == null ? "" : secs(seconds);
    }
  }
}

// --- the Live page: one to three panels ------------------------------------------------------

let panels: Panel[] = [];
function overview(): void {
  const box = q("live-overview"); box.replaceChildren();
  const rows = panels.map(p => p.summary).filter(s => s.run);
  box.hidden = panels.length < 2 || rows.length === 0; if (box.hidden) return;
  const table = mk("table", undefined, "live-table"); const head = mk("tr");
  head.append(...["Project", "Agent", "Status", "Tokens", "Time", "Quality"].map(t => mk("th", t))); table.append(head);
  for (const { project, run } of rows) {
    if (!run) continue; const v = run.verdict; const r = mk("tr");
    r.append(mk("td", project), mk("td", run.agent_name), mk("td", run.state), mk("td", v ? change(v.token_saving_pct) : "…", v?.token_saving_pct != null && v.token_saving_pct >= 0 ? "good" : ""), mk("td", v ? change(v.time_saving_pct) : "…"), mk("td", v ? v.quality.replace("_", " ") : "…"));
    table.append(r);
  }
  box.append(mk("h3", "All projects at a glance"), table);
}
function layout(count: number): void {
  const wrap = q("live-panels"); const saved = panels.map(p => p.config);
  while (panels.length > count) panels.pop()!.destroy();
  const projects = allProjects();
  while (panels.length < count) {
    const used = new Set(panels.map(p => p.config.project));
    const free = projects.find(p => p.state === "ready" && !used.has(p.id)) ?? projects.find(p => p.id === selectedProject()) ?? projects[0];
    const panel = new Panel(free?.id ?? "", overview); panels.push(panel);
    const wanted = saved[panels.length - 1]; if (wanted) panel.setAgent(wanted.agent);
  }
  wrap.className = `live-panels n${count}`; wrap.replaceChildren(...panels.map(p => p.el));
  document.querySelectorAll<HTMLElement>("[data-live-count]").forEach(b => b.classList.toggle("on", Number(b.dataset.liveCount) === count));
  try { localStorage.setItem("prism-live-count", String(count)); } catch { /* Optional. */ }
  overview();
}

// --- Compare page: history of finished runs ---------------------------------------------------

async function history(): Promise<void> {
  const box = q("compare-history"); const detail = q("compare-detail");
  try {
    const rows = await call<Row[]>("live/history");
    box.replaceChildren();
    if (!rows.length) { box.append(mk("p", "No live comparisons for this project yet. Run one on the Live page and it appears here.", "muted")); detail.replaceChildren(); return; }
    const table = mk("table", undefined, "live-table"); const head = mk("tr");
    head.append(...["When", "Agent", "Task", "Tokens", "Time", "Commands", "Quality"].map(t => mk("th", t))); table.append(head);
    for (const row of rows) {
      const v = row.verdict; const r = mk("tr", undefined, "clickable"); r.tabIndex = 0;
      r.append(mk("td", new Date(row.started * 1000).toLocaleString()), mk("td", row.agent_name), mk("td", row.task.length > 70 ? `${row.task.slice(0, 70)}…` : row.task),
        mk("td", v ? `${fmt(row.without.usage?.total_tokens)} → ${fmt(row.with.usage?.total_tokens)} (${change(v.token_saving_pct)})` : row.state, v?.token_saving_pct != null && v.token_saving_pct >= 0 ? "good" : ""),
        mk("td", v ? `${secs(row.without.duration_seconds)} → ${secs(row.with.duration_seconds)}` : ""), mk("td", v ? `${row.without.commands_run} → ${row.with.commands_run}` : ""), mk("td", v ? v.quality.replace("_", " ") : row.state));
      const open = (): void => { void call<LiveRun>(`live/runs/${row.id}`).then(run => showDetail(detail, run)).catch(e => say(String(e), true)); };
      r.addEventListener("click", open); r.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
      table.append(r);
    }
    box.append(table);
  } catch (error) { box.replaceChildren(mk("p", `Could not load history: ${error}`, "live-note warn")); }
}
function showDetail(detail: HTMLElement, run: LiveRun): void {
  detail.replaceChildren(mk("h3", `${run.agent_name}: ${run.task}`));
  const verdict = mk("div", undefined, "live-verdict"); detail.append(verdict); verdictBox(verdict, run);
  const grid = mk("div", undefined, "live-arms");
  for (const arm of ARMS) {
    const card = mk("article", undefined, `live-arm ${arm}`); card.append(mk("h3", TITLES[arm]));
    const feed = new Feed(mk("div", undefined, "live-feed terminal-feed"), "terminal"); card.append(mk("p", "Terminal commands that were run", "muted"), feed.el);
    for (const event of run.arms[arm].events) feed.add(event);
    card.append(...armDetails(run.arms[arm])); grid.append(card);
  }
  detail.append(grid);
}

export function initLive(): void {
  agents = [];
  const start = (): void => {
    let count = 1; try { count = Math.min(3, Math.max(1, Number(localStorage.getItem("prism-live-count")) || 1)); } catch { /* Optional. */ }
    layout(count);
  };
  document.querySelectorAll<HTMLElement>("[data-live-count]").forEach(b => b.addEventListener("click", () => layout(Number(b.dataset.liveCount))));
  onProjects(() => panels.forEach(p => p.fillSelects()));
  onProjectChange(() => { void history(); });
  window.addEventListener("hashchange", () => { if (location.hash === "#compare") void history(); });
  window.setInterval(() => panels.forEach(p => p.tick()), 500);
  void call<{ agents: AgentInfo[] }>("live/status", undefined, null).then(status => { agents = status.agents; panels.forEach(p => p.fillSelects()); }).catch(() => undefined);
  const ready = (): void => { if (allProjects().length) start(); else window.setTimeout(ready, 150); };
  ready();
  if (location.hash === "#compare") void history();
}

