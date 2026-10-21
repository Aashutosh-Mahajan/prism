// Small helpers shared by the dashboard pages: the selected project, API calls and text formatting.
// Anything that comes from an agent or a repository is untrusted: it is only inserted with textContent.

export interface Project {
  id: string; name: string; root: string; source: "path" | "git"; url: string | null;
  state: "ready" | "needs_index" | "cloning" | "indexing" | "failed" | "missing"; error: string | null;
  default: boolean; files: number | null; symbols: number | null; last_scan: string | null;
}

let current: string | null = null;
const listeners: Array<(id: string | null) => void> = [];
export const selectedProject = (): string | null => current;
export function setSelectedProject(id: string | null, announce = true): void {
  if (id === current) return;
  current = id;
  if (announce) listeners.forEach(listener => listener(id));
}
export function onProjectChange(listener: (id: string | null) => void): void { listeners.push(listener); }

export async function call<T>(path: string, body?: unknown, project?: string | null): Promise<T> {
  const chosen = project === undefined ? current : project;
  const headers: Record<string, string> = body === undefined ? {} : { "Content-Type": "application/json" };
  if (chosen) headers["X-Prism-Project"] = chosen;
  const response = await fetch(`/api/dashboard/${path}`, {
    credentials: "same-origin", headers, method: body === undefined ? "GET" : "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message ?? data.error ?? `Request failed (${response.status})`);
  return data as T;
}

export const q = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;
export const mk = (tag: string, text?: string, cls?: string): HTMLElement => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
export function say(message: string, error = false): void {
  const box = q("notification");
  if (!box) return;
  box.textContent = message; box.hidden = false; box.classList.toggle("error", error);
  window.setTimeout(() => { if (box.textContent === message) box.hidden = true; }, 9000);
}
export const fmt = (n: number | null | undefined): string => n == null ? "n/a" : n.toLocaleString();
export const money = (n: number | null | undefined): string => n == null ? "n/a" : `$${n.toFixed(4)}`;
export const secs = (n: number | null | undefined): string => n == null ? "n/a" : n >= 90 ? `${Math.floor(n / 60)} min ${Math.round(n % 60)} s` : `${n.toFixed(1)} s`;
export const change = (pct: number | null | undefined): string => pct == null ? "n/a" : pct >= 0 ? `${pct.toFixed(1)}% less` : `${(-pct).toFixed(1)}% more`;
