// Theme tokens read from CSS custom properties, so the canvas and the chrome always agree.
import { setTheme, type Theme } from "./encode";
import { store, stored } from "./ui";

export interface Palette {
  edge: string;
  edgeWeak: string;
  label: string;
  faded: string;
  accent: string;
  danger: string;
  canvas: string;
  chrome: string;
  rule: string;
  rings: string[];
  diff: Record<string, string>;
}

export const palette: Palette = {
  edge: "", edgeWeak: "", label: "", faded: "", accent: "", danger: "", canvas: "", chrome: "", rule: "",
  rings: [], diff: {},
};

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function readPalette(): void {
  setTheme(currentTheme());
  Object.assign(palette, {
    edge: token("--edge"),
    edgeWeak: token("--edge-weak"),
    label: token("--label"),
    faded: token("--faded"),
    accent: token("--accent"),
    danger: token("--danger"),
    canvas: token("--ink"),
    chrome: token("--slate"),
    rule: token("--rule"),
    rings: ["", token("--ring-1"), token("--ring-2"), token("--ring-3"), token("--ring-4")],
    diff: { A: token("--diff-a"), M: token("--diff-m"), D: token("--diff-d"), R: token("--accent") },
  });
}

export function initTheme(): void {
  const saved = stored("prism-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  else if (matchMedia("(prefers-color-scheme: light)").matches) document.documentElement.dataset.theme = "light";
  readPalette();
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  store("prism-theme", next);
  readPalette();
  return next;
}

/** `color` (#rgb, #rrggbb or rgb()) with an alpha channel. */
export function withAlpha(color: string, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha));
  if (color.startsWith("#")) {
    let hex = color.slice(1);
    if (hex.length === 3) hex = [...hex].map((c) => c + c).join("");
    const n = parseInt(hex.slice(0, 6), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  const m = color.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b] = m[1].split(",").map((v) => parseFloat(v));
    return `rgba(${r},${g},${b},${a})`;
  }
  return color;
}
