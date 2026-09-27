// Node inspector. Renders immediately from what the graph already knows (identity, metrics,
// connections in view), then enriches itself with the server's context pack. Every reference
// is a button that navigates to that node.
import type { App } from "./app";
import { KIND_LABELS } from "./app";
import type { Details, GNode, Layer } from "./types";
import { $, el, formatAgo, plural, stored, toast } from "./ui";

const LIST_LIMIT = 12;

const RELATION_WORDS: Record<Layer, [string, string]> = {
  import: ["Imported by", "Imports"],
  call: ["Called by", "Calls"],
  tests: ["Tested by", "Tests"],
  cochange: ["Changes with", "Changes with"],
  routes: ["Reached from", "Leads to"],
};

interface LinkItem {
  ref: string;
  label?: string;
  meta?: string;
}

function shortName(ref: string): string {
  const cleaned = ref.replace(/^pkg:/, "");
  if (cleaned.includes("/")) return cleaned.split("/").pop() ?? cleaned;
  const parts = cleaned.split(".");
  return parts.length > 1 ? parts.slice(-2).join(".") : cleaned;
}

function linkList(app: App, items: LinkItem[]): HTMLElement {
  const ul = el("ul", { class: "links" });
  const render = (limit: number) => {
    ul.replaceChildren();
    for (const it of items.slice(0, limit)) {
      const target = app.mapToNode(it.ref);
      const color = target ? (app.graph.getNodeAttribute(target, "color") as string) : "transparent";
      const button = el("button", { type: "button", title: it.ref }, [
        el("span", { class: "sw", style: `background:${color}`, "aria-hidden": "true" }),
        el("span", { class: "l-name" }, [it.label ?? shortName(it.ref)]),
        it.meta ? el("span", { class: "l-meta" }, [it.meta]) : null,
      ]);
      button.addEventListener("click", () => app.jumpTo(it.ref));
      if (target) {
        const hover = (on: boolean) => {
          app.state.hovered = on ? target : null;
          app.refresh();
        };
        button.addEventListener("mouseenter", () => hover(true));
        button.addEventListener("mouseleave", () => hover(false));
        button.addEventListener("focus", () => hover(true));
        button.addEventListener("blur", () => hover(false));
      }
      ul.append(el("li", {}, [button]));
    }
    if (items.length > limit) {
      const more = el("button", { type: "button", class: "more" }, [`Show ${items.length - limit} more`]);
      more.addEventListener("click", () => {
        render(items.length);
        (ul.children[limit]?.querySelector("button") as HTMLButtonElement | null)?.focus();
      });
      ul.append(el("li", {}, [more]));
    }
  };
  render(LIST_LIMIT);
  return ul;
}

function section(title: string, count: number | null, body: Node, open = true): HTMLDetailsElement {
  return el("details", { class: "section", open }, [
    el("summary", {}, [title, count !== null ? el("span", { class: "n" }, [count]) : null]),
    body,
  ]) as HTMLDetailsElement;
}

function stat(label: string, value: string | number, small?: string): HTMLElement {
  return el("div", { class: "stat" }, [el("dt", {}, [label]), el("dd", {}, [String(value), small ? el("small", {}, [` ${small}`]) : null])]);
}

function editorLink(editor: { path: string; line: number }): string {
  const scheme = stored("prism-editor") ?? "vscode";
  const path = editor.path.startsWith("/") ? editor.path : `/${editor.path}`;
  if (scheme === "idea") return `idea://open?file=${encodeURIComponent(editor.path)}&line=${editor.line}`;
  return `${scheme}://file${encodeURI(path)}:${editor.line}`;
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied “${text}”`);
  } catch {
    toast(text);
  }
}

function header(app: App, id: string, n: GNode | null, body: HTMLElement): void {
  const kind = n?.kind ?? "node";
  const color = n ? (app.graph.getNodeAttribute(id, "color") as string) : "var(--dim)";
  body.append(
    el("div", { class: "ins-kind" }, [el("span", { class: "sw", style: `background:${color}`, "aria-hidden": "true" }), KIND_LABELS[kind] ?? kind]),
    el("h2", { class: "ins-title", id: "ins-title", tabindex: "-1" }, [n?.label ?? shortName(id)]),
  );
  const fullId = n?.kind === "cluster" ? n.group : n?.module && n.kind !== "module" && n.kind !== "test" ? id : n?.module ?? id;
  if (fullId && fullId !== n?.label) body.append(el("p", { class: "ins-id" }, [fullId]));
  if (n?.file) {
    const lines = n.lines ? `:${n.lines[0]}–${n.lines[1]}` : "";
    body.append(el("div", { class: "ins-loc" }, [`${n.file}${lines}`]));
  }
  const badges = el("div", { class: "badges" });
  if (n?.entry_point) badges.append(el("span", { class: "badge" }, ["entry point"]));
  if (n?.dead) badges.append(el("span", { class: "badge warn" }, ["possibly unused"]));
  if (n?.findings) badges.append(el("span", { class: "badge bad" }, [plural(n.findings, "open finding")]));
  if (n?.change) badges.append(el("span", { class: "badge warn" }, [`changed (${n.change})`]));
  if (n?.test) badges.append(el("span", { class: "badge" }, ["test code"]));
  if (badges.childElementCount) body.append(badges);
  if (n?.signature) body.append(el("div", { class: "ins-sig" }, [n.signature]));
  if (n?.doc) body.append(el("p", { class: "ins-doc" }, [n.doc]));

  if (n) {
    const incoming = app.rel.incoming.get(id)?.length ?? 0;
    const outgoing = app.rel.outgoing.get(id)?.length ?? 0;
    const pct = app.importancePercentile(id);
    const stats = el("dl", { class: "stats" }, [
      stat("Importance", pct >= 50 ? `Top ${Math.max(1, 100 - pct)}%` : `${pct}th`, ""),
      stat("Incoming", incoming),
      stat("Outgoing", outgoing),
      stat(n.kind === "cluster" ? "Files" : "Lines", n.kind === "cluster" ? n.files ?? 0 : n.loc),
      stat("Risk", `${Math.round(n.risk * 100)}%`),
      stat("Blast", n.blast, n.blast === 1 ? "file" : "files"),
    ]);
    body.append(stats);
  }
}

function actions(app: App, id: string, n: GNode | null, d: Details | null): HTMLElement {
  const row = el("div", { class: "actions" });
  if (d?.editor) row.append(el("a", { href: editorLink(d.editor), title: "Open this code in your editor" }, ["Open in editor"]));
  if (n?.kind === "cluster") row.append(el("button", { type: "button", onclick: () => app.drillInto(n) }, ["Open package"]));
  if (n && app.state.level === "file" && n.kind !== "cluster") {
    row.append(el("button", { type: "button", onclick: () => app.openNode(id) }, ["Show its symbols"]));
  }
  row.append(el("button", { type: "button", title: "Keyboard: L", onclick: () => app.setRoot(id) }, ["Focus neighbourhood"]));
  if (n?.kind !== "cluster" && n?.kind !== "route") {
    row.append(el("button", { type: "button", title: "Keyboard: B", onclick: () => void app.showBlast(id) }, ["What depends on this"]));
  }
  const command = d?.context_command ?? (n?.kind !== "cluster" ? `prism context ${n?.module && n.kind === "module" ? n.module : id}` : null);
  if (command) row.append(el("button", { type: "button", title: command, onclick: () => void copy(command) }, ["Copy agent command"]));
  return row;
}

function inView(app: App, id: string, body: HTMLElement): Set<string> {
  const [inWord, outWord] = RELATION_WORDS[app.state.layer];
  const incoming = app.rel.incoming.get(id) ?? [];
  const outgoing = app.rel.outgoing.get(id) ?? [];
  const toItems = (ids: string[]): LinkItem[] =>
    ids
      .map((ref) => app.node(ref))
      .filter((m): m is GNode => m !== null)
      .sort((a, b) => b.rank - a.rank)
      .map((m) => ({ ref: m.id, label: m.label, meta: m.kind === "cluster" ? `package · ${plural(m.files ?? 0, "file")}` : m.file ?? "" }));
  if (incoming.length) body.append(section(inWord, incoming.length, linkList(app, toItems(incoming))));
  if (outgoing.length && !(app.state.layer === "cochange" && incoming.length)) {
    body.append(section(outWord, outgoing.length, linkList(app, toItems(outgoing))));
  }
  if (!incoming.length && !outgoing.length) {
    body.append(el("p", { class: "hint" }, ["No connections in this view. Try another layer, or zoom out a level."]));
  }
  return new Set([...incoming, ...outgoing]);
}

function enrich(app: App, n: GNode | null, d: Details, body: HTMLElement, shown: Set<string>): void {
  if (d.kind === "cluster") {
    if (d.summary) {
      const text = String(d.summary)
        .replace(/<!--.*?-->/g, "")
        .replace(/^# .*$/m, "")
        .replace(/_Not written yet[^_]*_/g, "")
        .trim();
      if (text) body.append(section("Summary", null, el("div", { class: "summary-text" }, [text])));
    }
    body.append(section("Files", d.files.length, linkList(app, d.files.map((f: string) => ({ ref: f }))), false));
    return;
  }
  if (d.kind === "route") {
    body.append(section("Handler", 1, linkList(app, [{ ref: d.handler, meta: `${d.file}:${d.line}` }])));
    return;
  }
  const pack = d.pack ?? {};
  if (pack.summary && !n?.doc) body.append(el("p", { class: "ins-doc" }, [pack.summary]));
  if (pack.risk && (pack.risk.score || pack.risk.reasons?.length)) {
    const riskBody = el("div", {}, [
      el("div", { class: "riskbar", role: "img", "aria-label": `Risk ${Math.round(pack.risk.score * 100)} percent` }, [
        el("i", { style: `width:${Math.round(pack.risk.score * 100)}%` }),
      ]),
      pack.risk.reasons?.length ? el("ul", { class: "reasons" }, pack.risk.reasons.map((r: string) => el("li", {}, [r]))) : null,
    ]);
    body.append(section(`Why it's risky · ${Math.round(pack.risk.score * 100)}%`, null, riskBody));
  }
  if (d.findings?.length) {
    const list = el("div", {}, d.findings.map((f: any) =>
      el("div", { class: "finding" }, [el("b", {}, [`${f.id} · ${f.severity}`]), el("div", {}, [f.title])]),
    ));
    body.append(section("Open audit findings", d.findings.length, list));
  }
  const lists: [string, LinkItem[], boolean][] = [
    ["All callers", (pack.callers ?? []).map((c: any) => ({ ref: c.id, meta: `${c.file}:${c.line}` })), true],
    ["All callees", (pack.callees ?? []).map((c: any) => ({ ref: c.id, meta: c.file })), true],
    ["Members", (pack.members ?? []).map((m: string) => ({ ref: `${pack.target?.id}.${m.split("(")[0]}`, label: m })), true],
    ["Defines", (pack.symbols ?? []).map((s: any) => ({ ref: s.id, meta: s.kind })), true],
    ["Imports", (pack.imports ?? []).map((m: string) => ({ ref: m })), false],
    ["Imported by", (pack.imported_by ?? []).map((m: string) => ({ ref: m })), false],
    ["Tests", (pack.tests ?? []).map((m: string) => ({ ref: m })), true],
    ["Often changed with", (pack.co_changed ?? []).map((m: string) => ({ ref: m })), false],
  ];
  for (const [title, items, open] of lists) {
    // Skip lists that only repeat the connections already shown for this view.
    const adds = items.some((it) => {
      const target = app.mapToNode(it.ref);
      return !target || !shown.has(target);
    });
    if (items.length && adds) body.append(section(title, items.length, linkList(app, items), open));
  }
  if (pack.blast_radius?.files) {
    body.append(section(`Could break · ${plural(pack.blast_radius.files, "file")}`, null,
      linkList(app, (pack.blast_radius.top ?? []).map((f: string) => ({ ref: f }))), false));
  }
  if (d.owners?.length || d.churn || n?.last_changed) {
    const git = el("p", { class: "hint" }, [
      `${plural(d.churn ?? 0, "commit")} · last changed ${formatAgo(n?.last_changed)} · ${d.owners?.length ? `mostly ${d.owners.join(", ")}` : "owner unknown"}`,
    ]);
    body.append(section("History", null, git, false));
  }
  if (d.smells?.length) {
    const list = el("ul", { class: "reasons" }, d.smells.map((s: any) => el("li", {}, [`Line ${s.line}: ${s.detail}`])));
    body.append(section("Things to double-check", d.smells.length, list, false));
  }
}

export function renderInspector(app: App, id: string, focusPanel: boolean): void {
  const panel = $("panel");
  const body = $("panel-body");
  if (panel.hidden) app.rememberFocus();
  panel.hidden = false;
  body.replaceChildren();
  const n = app.node(id);
  header(app, id, n, body);
  const actionRow = actions(app, id, n, null);
  body.append(actionRow);
  const shown = n ? inView(app, id, body) : new Set<string>();
  const loading = el("div", { "aria-hidden": "true" }, [el("div", { class: "skeleton" }), el("div", { class: "skeleton", style: "width:70%" })]);
  body.append(loading);
  if (focusPanel) $("ins-title").focus();

  app.details(id).then(
    (d: Details) => {
      if (app.state.selected !== id) return;
      loading.remove();
      actionRow.replaceWith(actions(app, id, n, d));
      enrich(app, n, d, body, shown);
    },
    (err: unknown) => {
      if (app.state.selected !== id) return;
      loading.replaceWith(el("p", { class: "hint" }, [err instanceof Error ? `More details are unavailable: ${err.message}` : "More details are unavailable."]));
    },
  );
}
