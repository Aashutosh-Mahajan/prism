import "./live-compare.css";
import { allProjects, onProjects } from "./projects";
import { call, change, fmt, mk, money, onProjectChange, q, say, secs, selectedProject } from "./shared";

// Live paired runs. Each panel runs one project and one agent twice at once (without and with PRISM) and
// streams messages, terminal commands and token counters. Several panels show several projects together.

interface LiveEvent { kind: "info" | "text" | "tool" | "result" | "terminal_start" | "terminal_end"; text?: string; name?: string; ok?: boolean; id?: string; command?: string; output?: string; phase?: string; t: number }
type Usage = { input_tokens: number; cache_creation_tokens: number; cache_read_tokens: number; output_tokens: number; input_total: number; total_tokens: number };
interface Check { ran: boolean; passed: boolean; exit_code: number | null; output: string; seconds: number }
interface ArmState {
  state: string; events: LiveEvent[]; event_count: number; usage: Usage | null; usage_final: boolean; turns: number | null;
  started: number | null; finished: number | null; duration_seconds: number | null; cost_usd: number | null; commands_run: number;
  final_text: string; error: string | null; patch: string; files_changed: string[]; lines_added: number; lines_removed: number; check: Check | null;
}
interface Verdict {
  quality: string; token_saving_pct: number | null; input_saving_pct: number | null; output_saving_pct: number | null; cost_saving_pct: number | null;
  time_saving_pct: number | null; commands_saving_pct: number | null; identical_patch: boolean; no_changes?: boolean;
}
interface Spread { median: number; min: number; max: number }
interface Batch {
  id: string; index: number; total: number;
  summary?: { done: number; total: number; token_saving_pct: Spread | null; time_saving_pct: Spread | null; wins: number; same_quality: number };
}
type Arms = Record<"without" | "with", ArmState>;
interface LiveRun {
  id: string; state: string; agent: string; agent_name: string; manual: boolean; task: string; check_command: string; model?: string; error: string | null;
  preparation: { arms: Record<"without" | "with", string> } | null; arms: Arms; verdict: Verdict | null; started: number; finished: number | null;
  manual_launch?: Record<"without" | "with", string>; batch?: Batch | null;
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
      if (event.phase === "verification") block.append(mk("div", "VERIFICATION COMMAND", "instrument-label"));
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
  row(run.manual ? "Manual hand-off time" : "Time", secs(a.duration_seconds), secs(b.duration_seconds), run.manual ? "n/a" : change(v.time_saving_pct), run.manual ? null : v.time_saving_pct);
  row("Agent terminal commands", run.manual ? "Not captured" : fmt(a.commands_run), run.manual ? "Not captured" : fmt(b.commands_run), run.manual ? "n/a" : change(v.commands_saving_pct), run.manual ? null : v.commands_saving_pct);
  row("Agent turns", fmt(a.turns), fmt(b.turns));
  row("Lines changed", `+${a.lines_added} −${a.lines_removed}`, `+${b.lines_added} −${b.lines_removed}`, v.identical_patch ? "identical changes" : "different changes");
  if (run.check_command) row("Check passed", a.check?.passed ? "yes" : "NO", b.check?.passed ? "yes" : "NO", "", a.check?.passed && b.check?.passed ? 1 : -1);
  return table;
}
function spread(x: Spread | null | undefined): string { return x ? `${change(x.median)} (range ${change(x.min)} to ${change(x.max)})`.replace(/PRISM used /g, "") : "not measured"; }
function verdictBox(box: HTMLElement, run: { arms: Arms; check_command: string; verdict: Verdict | null; state: string; manual?: boolean; batch?: Batch | null }): void {
  box.replaceChildren();
  if (!run.verdict || ACTIVE.includes(run.state)) { box.hidden = true; return; }
  box.hidden = false; const v = run.verdict;
  const saving = v.token_saving_pct == null ? "Tokens could not be measured for this run." : `PRISM used ${change(v.token_saving_pct)} tokens${v.time_saving_pct == null ? "" : ` and ${change(v.time_saving_pct)} time`}.`;
  const text: Record<string, [string, string]> = {
    same: ["Both checks passed", `The configured check passed in both copies. ${saving}`],
    degraded: ["Quality dropped with PRISM", `The check passed without PRISM but failed with it. ${saving} A saving does not count when the result is worse.`],
    better: ["PRISM passed where the baseline failed", `${saving} One run is one example, not proof.`],
    both_failed: ["Both checks failed", "Review the check output below. A missing test, dependency, or code failure can cause this result; successful solutions have not been verified."],
    unverified: ["Quality not verified", `No check command was given, so nothing proves the output is still correct. ${saving} Add a test command to prove quality.`],
    incomplete: ["A run did not finish", "No comparison is shown because at least one agent failed or was stopped."],
  };
  const [title, body] = text[v.quality] ?? ["Result", ""];
  box.className = `live-verdict ${v.quality}`;
  const parts: HTMLElement[] = [mk("strong", title), mk("p", body)];
  if (run.manual) parts.push(mk("p", "Manual Antigravity run: PRISM does not capture agent tokens, cost, turns, or terminal commands. The Terminal tab shows PRISM's verification command. Time measures the manual hand-off interval.", "muted"));
  if (run.manual && !run.arms.without.files_changed.length && !run.arms.with.files_changed.length) parts.push(mk("p", "No source changes were recorded in either copy. For a coding task, finish the task in both Antigravity folders before checking the results.", "live-note warn"));
  if (v.no_changes && !run.manual) parts.push(mk("p", "Neither copy changed any file, so these numbers compare two runs that did no work. Check the Activity tab for what the agents did.", "live-note warn"));
  const batch = run.batch;
  if (batch && batch.summary && batch.summary.done > 0) {
    const b = batch.summary;
    parts.push(mk("p", `Batch of ${b.total}: ${b.done} finished. Median tokens ${spread(b.token_saving_pct)}; median time ${spread(b.time_saving_pct)}. PRISM used fewer tokens in ${b.wins} of ${b.done}; quality matched in ${b.same_quality} of ${b.done}.`, "live-note"));
  } else if (batch) parts.push(mk("p", `Run ${batch.index} of ${batch.total} in this batch.`, "muted"));
  if (run.check_command) parts.push(mk("pre", run.check_command, "verification-command"));
  if (v.quality !== "incomplete") parts.push(metricsTable(run, v), mk("p", "One paired run is one example. It shows what happened on this task, not a typical saving.", "muted"));
  box.append(...parts);
}
function armDetails(arm: ArmState): HTMLElement[] {
  const out: HTMLElement[] = [];
  if (arm.error) out.push(mk("p", `Problem: ${arm.error}`, "live-note warn"));
  const detail = (title: string, text: string, open = false): void => { if (!text) return; const d = mk("details") as HTMLDetailsElement; d.open = open; d.append(mk("summary", title), mk("pre", text)); out.push(d); };
  detail("Final answer", arm.final_text);
  detail(`Code changes (${arm.files_changed.length} file${arm.files_changed.length === 1 ? "" : "s"}, +${arm.lines_added} −${arm.lines_removed})`, arm.patch);
  if (arm.check) detail(`Check: ${arm.check.passed ? "passed" : "FAILED"} · exit ${arm.check.exit_code ?? "unavailable"}`, arm.check.output || "The command produced no output.", !arm.check.passed);
  return out;
}

// --- one live panel --------------------------------------------------------------------------

class Panel {
  readonly el = mk("section", undefined, "panel live-panel");
  private projectId: string; private agent = "claude"; private run: LiveRun | null = null; private timer: number | undefined;
  private destroyed = false;
  private revision = 0;
  private starting = false;
  private offsets = { without: 0, with: 0 };
  private feeds = {} as Record<"without" | "with", { activity: Feed; terminal: Feed }>;
  private ui = {} as Record<string, HTMLElement>;

  constructor(projectId: string, private readonly changed: () => void) { this.projectId = projectId; this.build(); void this.load(); }

  private field<T extends HTMLElement>(tag: string, cls = "", text?: string): T { return mk(tag, text, cls) as T; }
  private build(): void {
    const ui = this.ui;
    const bar = mk("div", undefined, "live-bar");
    ui.project = this.field("select"); ui.agent = this.field("select");
    (ui.project as HTMLSelectElement).addEventListener("change", () => { this.setProject((ui.project as HTMLSelectElement).value); panels.forEach(panel => panel.fillSelects()); });
    (ui.agent as HTMLSelectElement).addEventListener("change", () => { this.agent = (ui.agent as HTMLSelectElement).value; this.agentNote(); this.changed(); });
    const label = (text: string, input: HTMLElement): HTMLElement => { const l = mk("label", undefined, "live-field"); l.append(mk("span", text), input); return l; };
    bar.append(label("Project", ui.project), label("Coding agent", ui.agent));
    ui.task = this.field("textarea"); (ui.task as HTMLTextAreaElement).rows = 3; (ui.task as HTMLTextAreaElement).placeholder = "What should the agent change? For example: Add input validation to the signup form";
    ui.check = this.field("input"); (ui.check as HTMLInputElement).placeholder = "for example: python -m pytest -q";
    ui.model = this.field("input"); (ui.model as HTMLInputElement).placeholder = "agent default";
    ui.turns = this.field("input"); (ui.turns as HTMLInputElement).type = "number"; (ui.turns as HTMLInputElement).value = "30";
    ui.repeats = this.field("input"); (ui.repeats as HTMLInputElement).type = "number"; (ui.repeats as HTMLInputElement).min = "1"; (ui.repeats as HTMLInputElement).max = "5"; (ui.repeats as HTMLInputElement).value = "1";
    const options = mk("details", undefined, "live-options"); const grid = mk("div", undefined, "live-grid2");
    grid.append(label("Model (optional)", ui.model), label("Max turns (Claude Code)", ui.turns), label("Repeat the pair (1 to 5, uses real tokens each time)", ui.repeats)); options.append(mk("summary", "More options"), grid);
    ui.agentNote = mk("p", undefined, "live-note");
    ui.start = this.field("button", "primary-button", "Start comparison ↗"); (ui.start as HTMLButtonElement).type = "button";
    ui.stop = this.field("button", "quiet-button", "Stop both runs"); (ui.stop as HTMLButtonElement).type = "button"; ui.stop.hidden = true;
    (ui.start as HTMLButtonElement).addEventListener("click", () => { void this.start(); });
    (ui.stop as HTMLButtonElement).addEventListener("click", () => { void call("live/cancel", {}, this.projectId).catch(e => say(String(e), true)); });
    const actions = mk("div", undefined, "live-actions"); actions.append(ui.start, ui.stop);
    const form = mk("div", undefined, "live-form");
    const fields = mk("div", undefined, "live-setup");
    const setupHeading = mk("div", undefined, "setup-heading");
    ui.graph = mk("a", "Project graph ↗", "instrument-label"); (ui.graph as HTMLAnchorElement).target = "_blank"; (ui.graph as HTMLAnchorElement).rel = "noopener";
    setupHeading.append(mk("h2", "Set the conditions."), ui.graph);
    fields.append(setupHeading, bar, label("Task brief", ui.task), label("Verification command", ui.check), options, ui.agentNote, actions);
    const monitor = mk("aside", undefined, "run-monitor");
    ui.monitor = monitor;
    ui.monitorState = mk("strong", "Standby", "monitor-state");
    const dial = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    dial.setAttribute("viewBox", "0 0 160 160"); dial.setAttribute("class", "instrument-dial"); dial.setAttribute("aria-hidden", "true");
    for (let i = 0; i < 40; i++) {
      const tick = document.createElementNS(dial.namespaceURI, "line");
      tick.setAttribute("x1", "80"); tick.setAttribute("y1", i % 5 === 0 ? "16" : "22"); tick.setAttribute("x2", "80"); tick.setAttribute("y2", "32");
      tick.setAttribute("transform", `rotate(${i * 7.2 - 140} 80 80)`); tick.setAttribute("opacity", String(.18 + (i / 40) * .82)); dial.append(tick);
    }
    const center = document.createElementNS(dial.namespaceURI, "circle"); center.setAttribute("cx", "80"); center.setAttribute("cy", "80"); center.setAttribute("r", "12"); dial.append(center);
    ui.monitorHint = mk("p", "Configure a task to begin.", "monitor-hint");
    const protocol = mk("div", undefined, "monitor-protocol");
    for (const [n, title, detail] of [["01", "Prepare", "Two matching source copies"], ["02", "Execute", "Same task, with & without context"], ["03", "Verify", "Check results. Compare usage."]]) {
      const row = mk("div"); const text = mk("div"); text.append(mk("strong", title), mk("span", detail)); row.append(mk("span", n, "protocol-number"), text); protocol.append(row);
    }
    monitor.append(mk("span", "EXECUTION / STATUS", "instrument-label"), dial, ui.monitorState, ui.monitorHint, protocol);
    form.append(fields, monitor);
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
    (this.ui.graph as HTMLAnchorElement).href = `/?project=${encodeURIComponent(this.projectId)}`;
    const projectSelect = this.ui.project as HTMLSelectElement; const agentSelect = this.ui.agent as HTMLSelectElement;
    projectSelect.replaceChildren(...allProjects().map(p => { const o = document.createElement("option"); o.value = p.id; o.textContent = `${p.name}${p.state === "ready" ? "" : ` (${p.state.replace("_", " ")})`}`; o.disabled = p.state !== "ready" || panels.some(panel => panel !== this && panel.config.project === p.id); return o; }));
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
    this.revision++;
    this.run = null; this.offsets = { without: 0, with: 0 };
    for (const arm of ARMS) { this.feeds[arm].activity.reset(); this.feeds[arm].terminal.reset(); }
    this.ui.results.hidden = true;
    for (const field of ["agent", "task", "check", "model", "turns", "start"]) (this.ui[field] as HTMLInputElement).disabled = false;
    this.ui.stop.hidden = true;
    this.ui.monitor.dataset.active = "false";
    this.ui.monitorState.textContent = "Standby";
    this.ui.monitorHint.textContent = "Configure a task to begin.";
  }
  private stopPolling(): void { if (this.timer !== undefined) { clearTimeout(this.timer); this.timer = undefined; } }
  destroy(): void { this.destroyed = true; this.revision++; this.stopPolling(); }
  get summary(): { project: string; run: LiveRun | null } { return { project: allProjects().find(p => p.id === this.projectId)?.name ?? "project", run: this.run }; }
  get config(): { project: string; agent: string } { return { project: this.projectId, agent: this.agent }; }
  setAgent(agent: string): void { this.agent = agent; this.fillSelects(); }
  setProject(projectId: string): void { if (projectId === this.projectId || this.starting) return; if (!allProjects().some(project => project.id === projectId && project.state === "ready")) return; this.stopPolling(); this.projectId = projectId; this.reset(); this.fillSelects(); void this.load(); this.changed(); }

  private async load(): Promise<void> {
    const revision = this.revision;
    try { const project = this.projectId; const run = await call<LiveRun | null>(`live?without=0&with=0`, undefined, project); if (this.destroyed || revision !== this.revision) return;
      if (run) { this.agent = run.agent; this.fillSelects(); (this.ui.task as HTMLTextAreaElement).value = run.task; (this.ui.check as HTMLInputElement).value = run.check_command; (this.ui.model as HTMLInputElement).value = run.model ?? ""; }
      this.runId = run?.id ?? ""; this.render(run, true); if (this.more(run)) this.poll(); }
    catch (error) { if (!this.destroyed && revision === this.revision) say(`Could not load this project's live run: ${error}`, true); }
  }
  private runId = "";
  private more(run: LiveRun | null): boolean { return !!run && (ACTIVE.includes(run.state) || (run.state === "completed" && !!run.batch && run.batch.index < run.batch.total)); }
  private poll(): void {
    if (this.destroyed) return;
    this.stopPolling();
    const project = this.projectId;
    const revision = this.revision;
    this.timer = window.setTimeout(() => {
      void call<LiveRun | null>(`live?without=${this.offsets.without}&with=${this.offsets.with}`, undefined, project).then(run => {
        if (this.destroyed || revision !== this.revision) return; this.timer = undefined;
        const fresh = !!run && this.runId !== run.id; this.runId = run?.id ?? "";
        this.render(run, fresh); if (this.more(run)) this.poll();
      }).catch(error => { if (this.destroyed || revision !== this.revision) return; this.timer = undefined; say(`Live status unavailable: ${error}. Reconnecting…`, true); this.poll(); });
    }, 800);
  }
  private async start(): Promise<void> {
    if (this.starting || this.destroyed) return;
    const task = (this.ui.task as HTMLTextAreaElement).value.trim();
    if (!task) { say("Describe one coding task first.", true); return; }
    const revision = ++this.revision;
    this.stopPolling();
    const project = this.projectId;
    const selectionAtStart = selectedProject();
    this.starting = true;
    (this.ui.project as HTMLSelectElement).disabled = true;
    for (const field of ["agent", "task", "check", "model", "turns", "repeats"]) (this.ui[field] as HTMLInputElement).disabled = true;
    (this.ui.start as HTMLButtonElement).disabled = true;
    try {
      const run = await call<LiveRun>("live", {
        task, agent: this.agent, check_command: (this.ui.check as HTMLInputElement).value.trim(), model: (this.ui.model as HTMLInputElement).value.trim(),
        max_turns: Number((this.ui.turns as HTMLInputElement).value || 30), repeats: Number((this.ui.repeats as HTMLInputElement).value || 1),
      }, project);
      if (this.destroyed || revision !== this.revision) { say("The comparison started in the background. Reopen its project to follow it."); return; }
      this.render(run, true); this.poll();
    } catch (error) { if (!this.destroyed && revision === this.revision) { say(error instanceof Error ? error.message : String(error), true); (this.ui.start as HTMLButtonElement).disabled = false; for (const field of ["agent", "task", "check", "model", "turns", "repeats"]) (this.ui[field] as HTMLInputElement).disabled = false; } }
    finally { this.starting = false; if (!this.destroyed) { (this.ui.project as HTMLSelectElement).disabled = false; const chosen = selectedProject(); if (panels.length === 1 && chosen && chosen !== selectionAtStart) this.setProject(chosen); } }
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
    for (const field of ["agent", "task", "check", "model", "turns", "repeats"]) (this.ui[field] as HTMLInputElement).disabled = active;
    this.ui.monitor.dataset.active = String(active);
    this.ui.monitorState.textContent = run.state.replaceAll("_", " ");
    this.ui.monitorHint.textContent = active ? "Following both sandbox runs." : "Review the measured results below.";
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
        mk("small", usage ? `${state.usage_final ? "final" : "so far"} · input ${fmt(usage.input_total)} (cached ${fmt(usage.cache_read_tokens)}) · output ${fmt(usage.output_tokens)} · ${state.commands_run} command${state.commands_run === 1 ? "" : "s"}` : run.manual ? "Antigravity does not provide token counters to this dashboard." : "Token counts appear as the agent works"));
      this.feeds[arm].terminal.el.dataset.manual = String(run.manual);
      this.ui[`${arm}-extra`].replaceChildren(...armDetails(state));
    }
    this.tick(); verdictBox(this.ui.verdict, run);
  }
  private manualBox(run: LiveRun): void {
    const box = this.ui.manual;
    if (run.state !== "awaiting_manual" || !run.preparation) { box.hidden = true; box.replaceChildren(); delete box.dataset.run; return; }
    // Polling must preserve checkbox state, keyboard focus, and expanded launch instructions.
    if (!box.hidden && box.dataset.run === run.id) return;
    box.hidden = false; box.dataset.run = run.id; box.replaceChildren();
    const done = mk("button", "Done: check and compare", "primary-button") as HTMLButtonElement; done.type = "button";
    const confirmations: HTMLInputElement[] = [];
    const confirm = (text: string): HTMLElement => { const label = mk("label", undefined, "manual-confirm"); const input = document.createElement("input"); input.type = "checkbox"; confirmations.push(input); label.append(input, mk("span", text)); return label; };
    const without = confirm("I finished the task in the Without PRISM folder."); const withPrism = confirm("I finished the task in the With PRISM folder."); const unchanged = confirm("This task intentionally requires no source changes (optional).");
    const update = (): void => { done.disabled = !confirmations[0].checked || !confirmations[1].checked; }; confirmations.forEach(input => input.addEventListener("change", update)); update();
    done.addEventListener("click", () => { done.disabled = true; void call("live/finish", { allow_unchanged: confirmations[2].checked }, this.projectId).then(() => this.poll()).catch(e => { update(); say(String(e), true); }); });
    box.append(mk("h3", "Action required: run the task in Antigravity"), mk("p", "PRISM has prepared the folders. It does not open or run Antigravity automatically. Open each folder in a separate fresh conversation, use the same model and task, and save both solutions before continuing.", "muted"), mk("pre", run.task), mk("p", `Without PRISM: ${run.preparation.arms.without}`, "muted"), mk("p", `With PRISM: ${run.preparation.arms.with}`, "muted"), without, withPrism, unchanged, done);
    if (run.manual_launch) {
      const launch = mk("details"); launch.append(mk("summary", "Launch Antigravity with the correct PRISM environment"), mk("p", "Use a separate terminal for each command block (PowerShell on Windows). The With session needs its own consent configuration and PRISM on PATH. If antigravity is not recognized, launch its executable from that same terminal. Use a fresh app process so it inherits this environment.", "muted"));
      for (const arm of ARMS) launch.append(mk("h4", TITLES[arm]), mk("pre", run.manual_launch[arm]));
      box.insertBefore(launch, without);
    }
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
let desiredCount = 1;
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
  box.append(mk("h3", "All projects at a glance"), mk("p", "Each row compares that project's own baseline and PRISM run. Cross-project comparisons require matching tasks, models and checks.", "muted"), table);
}
function layout(count: number): void {
  count = Math.min(3, Math.max(1, Math.floor(count) || 1));
  desiredCount = count;
  const wrap = q("live-panels");
  const projects = allProjects().filter(project => project.state === "ready");
  const usedProjects = new Set<string>();
  panels = panels.filter(panel => { const id = panel.config.project; if (!projects.some(project => project.id === id) || usedProjects.has(id)) { panel.destroy(); return false; } usedProjects.add(id); return true; });
  count = Math.min(count, projects.length);
  while (panels.length > count) panels.pop()!.destroy();
  while (panels.length < count) {
    const used = new Set(panels.map(p => p.config.project));
    const free = (panels.length === 0 ? projects.find(p => p.id === selectedProject()) : undefined) ?? projects.find(p => p.state === "ready" && !used.has(p.id)) ?? projects[0];
    const panel = new Panel(free!.id, overview); panels.push(panel);
  }
  panels.forEach(panel => panel.fillSelects());
  wrap.className = `live-panels n${Math.max(1, count)}`; wrap.replaceChildren(...panels.map(p => p.el));
  if (!count) wrap.append(mk("p", "Add and index a project on the Projects page to begin a live comparison.", "panel muted"));
  document.querySelectorAll<HTMLButtonElement>("[data-live-count]").forEach(b => { const selected = Number(b.dataset.liveCount) === count; b.disabled = Number(b.dataset.liveCount) > projects.length; b.title = b.disabled ? `Requires ${b.dataset.liveCount} indexed projects` : ""; b.classList.toggle("on", selected); b.setAttribute("aria-pressed", String(selected)); b.setAttribute("aria-label", `${b.dataset.liveCount} project${b.dataset.liveCount === "1" ? "" : "s"}`); });
  try { localStorage.setItem("prism-live-count", String(desiredCount)); } catch { /* Optional. */ }
  overview();
}

// --- Compare page: history of finished runs ---------------------------------------------------

let historyGeneration = 0;
async function history(): Promise<void> {
  const box = q("compare-history"); const detail = q("compare-detail");
  const generation = ++historyGeneration;
  const project = selectedProject();
  detail.replaceChildren();
  box.replaceChildren(mk("p", "Loading this project's comparisons…", "muted"));
  try {
    const rows = await call<Row[]>("live/history", undefined, project);
    if (generation !== historyGeneration || project !== selectedProject()) return;
    box.replaceChildren();
    if (!rows.length) { box.append(mk("p", "No live comparisons for this project yet. Run one on the Live page and it appears here.", "muted")); detail.replaceChildren(); return; }
    const table = mk("table", undefined, "live-table"); const head = mk("tr");
    head.append(...["When", "Agent", "Task", "Tokens", "Time", "Commands", "Quality"].map(t => mk("th", t))); table.append(head);
    for (const row of rows) {
      const v = row.verdict; const r = mk("tr", undefined, "clickable"); r.tabIndex = 0;
      r.append(mk("td", new Date(row.started * 1000).toLocaleString()), mk("td", row.agent_name), mk("td", row.task.length > 70 ? `${row.task.slice(0, 70)}…` : row.task),
        mk("td", v ? `${fmt(row.without.usage?.total_tokens)} → ${fmt(row.with.usage?.total_tokens)} (${change(v.token_saving_pct)})` : row.state, v?.token_saving_pct != null && v.token_saving_pct >= 0 ? "good" : ""),
        mk("td", v ? `${secs(row.without.duration_seconds)} → ${secs(row.with.duration_seconds)}` : ""), mk("td", v ? `${row.without.commands_run} → ${row.with.commands_run}` : ""), mk("td", v ? v.quality.replace("_", " ") : row.state));
      const open = (): void => { const requested = ++historyGeneration; void call<LiveRun>(`live/runs/${row.id}`, undefined, project).then(run => { if (requested === historyGeneration && project === selectedProject()) showDetail(detail, run); }).catch(e => { if (requested === historyGeneration) say(String(e), true); }); };
      r.addEventListener("click", open); r.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
      table.append(r);
    }
    box.append(table);
  } catch (error) { if (generation === historyGeneration && project === selectedProject()) box.replaceChildren(mk("p", `Could not load history: ${error}`, "live-note warn")); }
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
  onProjects(() => layout(desiredCount));
  onProjectChange(id => { if (id && panels.length === 1) panels[0].setProject(id); void history(); });
  window.addEventListener("hashchange", () => { if (location.hash === "#compare") void history(); });
  window.setInterval(() => panels.forEach(p => p.tick()), 500);
  void call<{ agents: AgentInfo[] }>("live/status", undefined, null).then(status => { agents = status.agents; panels.forEach(p => p.fillSelects()); }).catch(() => undefined);
  start();
  if (location.hash === "#compare") void history();
}

