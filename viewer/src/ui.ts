// Tiny DOM helpers (no framework: the viewer must stay small and self-contained).

export function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing #${id}`);
  return node as T;
}

type Child = Node | string | number | null | undefined | false;
type Props = Record<string, string | boolean | ((e: Event) => void) | undefined>;

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Props = {}, children: Child[] = []): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === false) continue;
    if (typeof value === "function") node.addEventListener(key.replace(/^on/, ""), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  }
  return node;
}

let toastTimer: number | undefined;
export function toast(message: string, error = false): void {
  const box = $("toast");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.setAttribute("role", error ? "alert" : "status");
  box.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (box.hidden = true), error ? 7000 : 3500);
}

/** Polite announcement for screen readers (graph focus, results). */
export function announce(message: string): void {
  const region = $("graph-focus");
  region.textContent = "";
  // Clearing first makes repeated identical messages announce again. A timeout (not a frame)
  // still fires when the page isn't painting.
  window.setTimeout(() => (region.textContent = message), 30);
}

export function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function stored(key: string): string | null {
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function store(key: string, value: string): void {
  try {
    storage()?.setItem(key, value);
  } catch {
    /* storage can be unavailable (private mode, blocked site data) */
  }
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? word : many}`;
}

export function formatAgo(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "unknown";
  const days = Math.round((Date.now() / 1000 - epochSeconds) / 86400);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 45) return `${days} days ago`;
  if (days < 540) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}
