import "./live-compare.css";

// Live paired runs: the same task through Claude Code with and without PRISM, streamed as it happens.
// Agent output is untrusted text: it is only ever inserted with textContent.

type Usage = { input_tokens: number; cache_creation_tokens: number; cache_read_tokens: number; output_tokens: number; input_total: number; total_tokens: number };
interface LiveEvent { kind: "info" | "text" | "tool" | "result"; text: string; name?: string; ok?: boolean; t: number }
interface Check { ran: boolean; passed: boolean; exit_code: number | null; output: string; seconds: number }
interface ArmState {
  state: string; events: LiveEvent[]; event_count: number; usage: Usage | null; usage_final: boolean; turns: number | null;
  duration_seconds: number | null; cost_usd: number | null; final_text: string; error: string | null; patch: string; files_changed: string[]; check: Check | null;
}
interface Verdict { quality: string; token_saving_pct: number | null; input_saving_pct: number | null; output_saving_pct: number | null; cost_saving_pct: number | null; identical_patch: boolean }
interface LiveRun { id: string; state: string; task: string; check_command: string; error: string | null; arms: Record<"without" | "with", ArmState>; verdict: Verdict | null; started: number; finished: number | null }
interface LiveStatus { agent_found: boolean; agent_version: string | null; logged_in: boolean | null; running: boolean }

const ARMS = ["without", "with"] as const;
const q = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;
const mk = (tag: string, text?: string, cls?: string): HTMLElement => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
const fmt = (n: number | null | undefined): string => n == null ? "n/a" : n.toLocaleString();
const money = (n: number | null | undefined): string => n == null ? "n/a" : `$${n.toFixed(4)}`;
const secs = (n: number | null | undefined): string => n == null ? "n/a" : `${n.toFixed(1)} s`;
const change = (pct: number | null | undefined): string => pct == null ? "n/a" : pct >= 0 ? `${pct.toFixed(1)}% fewer` : `${(-pct).toFixed(1)}% more`;
const RUNNING = ["preparing", "running", "checking"];

let offsets = { without: 0, with: 0 };
let timer: number | undefined;
let busy = false;

async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/dashboard/${path}`, {
    credentials: "same-origin", headers: body === undefined ? {} : { "Content-Type": "application/json" },
    method: body === undefined ? "GET" : "POST", body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message ?? data.error ?? `Request failed (${response.status})`);
  return data as T;
}
function say(message: string, error = false): void {
  const box = q("notification"); box.textContent = message; box.hidden = false; box.classList.toggle("error", error);
  window.setTimeout(() => { if (box.textContent === message) box.hidden = true; }, 9000);
}
function feedLine(event: LiveEvent): HTMLElement {
  if (event.kind === "tool") { const row = mk("div", undefined, "ev-tool"); row.append(mk("b", `▸ ${event.name}`), mk("span", ` ${event.text}`)); return row; }
  if (event.kind === "result") return mk("div", `${event.ok ? "✓" : "✗"} ${event.text}`, `ev-result${event.ok ? "" : " bad"}`);
  return mk("div", event.text, event.kind === "info" ? "ev-info" : "ev-text");
}
function renderSteps(run: LiveRun): void {
  const order = ["preparing", "running", "checking", "completed"];
  const stopped = run.state === "failed" || run.state === "cancelled" || run.state === "interrupted";
  const index = stopped ? -1 : order.indexOf(run.state);
  const labels = ["1  Prepare two copies", "2  Run both agents", "3  Check both results", "4  Compare"];
  q("live-steps").replaceChildren(...labels.map((label, i) => mk("span", label, run.state === "completed" || i < index ? "done" : i === index ? "on" : "")));
}
function renderArm(name: "without" | "with", arm: ArmState): void {
  const feed = q(`live-feed-${name}`);
  const stick = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
  for (const event of arm.events) feed.append(feedLine(event));
  if (stick) feed.scrollTop = feed.scrollHeight;
  offsets[name] = arm.event_count;
  q(`live-state-${name}`).textContent = arm.state;
  const usage = arm.usage;
  q(`live-tokens-${name}`).replaceChildren(
    document.createTextNode(usage ? `${fmt(usage.total_tokens)} tokens` : "waiting…"),
    mk("small", usage ? `${arm.usage_final ? "final" : "so far"} · input ${fmt(usage.input_total)} (cached ${fmt(usage.cache_read_tokens)}) · output ${fmt(usage.output_tokens)}` : "Token counts appear as the agent works"),
  );
  const extra = q(`live-extra-${name}`); extra.replaceChildren();
  if (arm.error) extra.append(mk("p", `Problem: ${arm.error}`, "live-note warn"));
  const detail = (title: string, text: string): void => { if (!text) return; const d = mk("details"); d.append(mk("summary", title), mk("pre", text)); extra.append(d); };
  detail("Final answer", arm.final_text);
  detail(`Code changes (${arm.files_changed.length} file${arm.files_changed.length === 1 ? "" : "s"})`, arm.patch);
  if (arm.check) detail(`Check: ${arm.check.passed ? "passed" : "FAILED"}`, arm.check.output);
}
function metricsTable(run: LiveRun): HTMLElement {
  const a = run.arms.without; const b = run.arms.with; const v = run.verdict!;
  const table = mk("table", undefined, "live-table"); const head = mk("tr");
  head.append(...["Measure", "Without PRISM", "With PRISM", "Difference"].map(t => mk("th", t))); table.append(head);
  const row = (label: string, x: string, y: string, diff = "", cls = ""): void => { const r = mk("tr"); r.append(mk("td", label), mk("td", x), mk("td", y), mk("td", diff, cls)); table.append(r); };
  row("Total tokens", fmt(a.usage?.total_tokens), fmt(b.usage?.total_tokens), change(v.token_saving_pct), (v.token_saving_pct ?? 0) >= 0 ? "good" : "bad");
  row("Input tokens (all)", fmt(a.usage?.input_total), fmt(b.usage?.input_total), change(v.input_saving_pct));
  row("  of which cached reads", fmt(a.usage?.cache_read_tokens), fmt(b.usage?.cache_read_tokens));
  row("Output tokens", fmt(a.usage?.output_tokens), fmt(b.usage?.output_tokens), change(v.output_saving_pct));
  row("Cost reported by Claude Code", money(a.cost_usd), money(b.cost_usd), change(v.cost_saving_pct), (v.cost_saving_pct ?? 0) >= 0 ? "good" : "bad");
  row("Agent turns", fmt(a.turns), fmt(b.turns)); row("Time", secs(a.duration_seconds), secs(b.duration_seconds));
  row("Files changed", String(a.files_changed.length), String(b.files_changed.length), v.identical_patch ? "identical changes" : "different changes");
  if (run.check_command) row("Check passed", a.check?.passed ? "yes" : "NO", b.check?.passed ? "yes" : "NO", "", a.check?.passed && b.check?.passed ? "good" : "bad");
  return table;
}
function renderVerdict(run: LiveRun): void {
  const box = q("live-verdict"); box.replaceChildren();
  if (!run.verdict || RUNNING.includes(run.state)) { box.hidden = true; return; }
  box.hidden = false; const v = run.verdict;
  const saving = `PRISM used ${change(v.token_saving_pct)} tokens and ${change(v.cost_saving_pct)} cost.`;
  const text: Record<string, [string, string]> = {
    same: ["Same quality, fewer tokens", `The independent check passed in both runs. ${saving}`],
    degraded: ["Quality dropped with PRISM", `The check passed without PRISM but failed with it. ${saving} A saving does not count when the result is worse.`],
    better: ["PRISM passed where the baseline failed", `${saving} One run is one example, not proof.`],
    both_failed: ["Both solutions failed the check", "Neither result is correct, so no saving is meaningful."],
    unverified: ["Quality not verified", `No check command was given, so nothing proves the output is still correct. ${saving} Add a test command to prove quality.`],
    incomplete: ["A run did not finish", "No comparison is shown because at least one agent failed or was stopped."],
  };
  const [title, body] = text[v.quality] ?? ["Result", ""];
  box.className = `live-verdict ${v.quality}`;
  const parts: HTMLElement[] = [mk("strong", title), mk("p", body)];
  if (v.quality !== "incomplete") parts.push(mk("p", "One paired run is one example. It shows what happened on this task, not a typical saving.", "muted"), metricsTable(run));
  box.append(...parts);
}
function render(run: LiveRun | null, fresh = false): void {
  q("live-results").hidden = run === null;
  if (!run) return;
  if (fresh) { offsets = { without: 0, with: 0 }; ARMS.forEach(n => q(`live-feed-${n}`).replaceChildren()); }
  renderSteps(run);
  q("live-task").textContent = run.task;
  for (const name of ARMS) renderArm(name, run.arms[name]);
  const active = RUNNING.includes(run.state);
  q<HTMLButtonElement>("live-start").disabled = active || busy; q<HTMLButtonElement>("live-cancel").hidden = !active;
  const status = q("live-run-status");
  status.textContent = run.error ? run.error : run.state === "preparing" ? "Copying the repository twice and building PRISM's index for the With copy…" : run.state === "running" ? "Both agents are working at the same time." : run.state === "checking" ? "Running your check command in both results…" : run.state === "completed" ? "Finished." : `Run ${run.state}.`;
  status.className = run.error ? "live-note warn" : "live-note";
  renderVerdict(run);
}
function poll(): void {
  if (timer !== undefined) clearTimeout(timer);
  timer = window.setTimeout(() => {
    void call<LiveRun | null>(`live?without=${offsets.without}&with=${offsets.with}`).then(run => {
      timer = undefined; render(run);
      if (run && RUNNING.includes(run.state)) poll();
    }).catch(error => { timer = undefined; say(`Live status unavailable: ${error}`, true); });
  }, 800);
}
async function start(): Promise<void> {
  const task = q<HTMLTextAreaElement>("live-task-input").value.trim();
  if (!task) { say("Describe one coding task first.", true); return; }
  busy = true; q<HTMLButtonElement>("live-start").disabled = true;
  try {
    const turns = Number(q<HTMLInputElement>("live-turns").value || 30);
    const run = await call<LiveRun>("live", { task, check_command: q<HTMLInputElement>("live-check").value.trim(), model: q<HTMLInputElement>("live-model").value.trim(), max_turns: turns });
    render(run, true); poll();
  } catch (error) { say(error instanceof Error ? error.message : String(error), true); q<HTMLButtonElement>("live-start").disabled = false; }
  finally { busy = false; }
}
async function init(): Promise<void> {
  q("live-start").addEventListener("click", () => { void start(); });
  q("live-cancel").addEventListener("click", () => { void call("live/cancel", {}).then(() => say("Stopping both runs…")).catch(e => say(String(e), true)); });
  const note = q("live-agent");
  try {
    const status = await call<LiveStatus>("live/status");
    if (!status.agent_found) { note.textContent = "Claude Code was not found. Install it, or set PRISM_CLAUDE_BIN to its program, then reload."; note.className = "live-note warn"; }
    else if (status.logged_in === false) { note.textContent = `Claude Code ${status.agent_version ?? ""} is installed but NOT logged in, so a run will fail. Log in once with the command "claude auth login" (see the project notes), then reload this page.`; note.className = "live-note warn"; }
    else { note.textContent = `Claude Code found (${status.agent_version ?? "version unknown"}). Each run uses real tokens from your plan.`; note.className = "live-note"; }
  } catch { note.textContent = "Could not check for Claude Code."; note.className = "live-note warn"; }
  try { const run = await call<LiveRun | null>("live?without=0&with=0"); render(run, true); if (run && RUNNING.includes(run.state)) poll(); } catch { /* No earlier run. */ }
}
void init();
