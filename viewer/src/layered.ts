// Layered ("architecture") layout: dependency tiers as horizontal bands, foundations at the
// bottom, entry points at the top. Within a band, nodes are ordered by the average position of
// their neighbours (barycentre sweeps), which removes most edge crossings, and long rows wrap.
// Units are screen pixels at the fitted zoom, so a slot can be as wide as its label and the
// whole picture has the viewport's proportions. Pure and deterministic: unit-tested.

export interface LayerNode {
  id: string;
  tier: number;
  size: number;
  /** Colour key: nodes of one area start next to each other before the sweeps. */
  area: string;
  rank: number;
  /** Characters of the label drawn beside the node (0 for none). */
  label?: number;
}

export interface Band {
  tier: number; // -1 is the row of unconnected nodes
  top: number; // graph y of the band's upper edge (y grows upward)
  bottom: number;
  left: number; // graph x of the band's first node's left edge
  count: number;
}

export interface LayeredResult {
  positions: Map<string, { x: number; y: number }>;
  bands: Band[];
  width: number;
}

export interface Viewport {
  width: number;
  height: number;
}

const CHAR_PX = 6.8; // 11px monospace labels
const SLOT_PAD = 22;
const WRAP_GAP = 34;
const SWEEPS = 8;

function slotWidth(n: LayerNode): number {
  return n.size * 2 + SLOT_PAD + (n.label ? n.label * CHAR_PX + 8 : 0);
}

export function layeredPositions(
  nodes: LayerNode[],
  edges: { source: string; target: string }[],
  viewport: Viewport = { width: 1200, height: 800 },
): LayeredResult {
  const neighbours = new Map<string, string[]>();
  for (const { source, target } of edges) {
    if (source === target) continue;
    (neighbours.get(source) ?? neighbours.set(source, []).get(source)!).push(target);
    (neighbours.get(target) ?? neighbours.set(target, []).get(target)!).push(source);
  }
  // Unconnected nodes get their own row under the foundations instead of crowding tier 0.
  const tierOf = (n: LayerNode) => (neighbours.has(n.id) ? n.tier : -1);
  const rows = new Map<number, LayerNode[]>();
  for (const n of nodes) (rows.get(tierOf(n)) ?? rows.set(tierOf(n), []).get(tierOf(n))!).push(n);
  const tiers = [...rows.keys()].sort((a, b) => a - b);
  for (const t of tiers) {
    rows.get(t)!.sort((a, b) => a.area.localeCompare(b.area) || b.rank - a.rank || a.id.localeCompare(b.id));
  }

  // Order within rows: a normalised slot (0..1) per node, refined by barycentre sweeps that
  // alternate direction so both upper and lower neighbours pull.
  const slot = new Map<string, number>();
  const assign = (row: LayerNode[]) => row.forEach((n, i) => slot.set(n.id, row.length > 1 ? i / (row.length - 1) : 0.5));
  for (const t of tiers) assign(rows.get(t)!);
  for (let sweep = 0; sweep < SWEEPS; sweep++) {
    const order = sweep % 2 === 0 ? tiers : [...tiers].reverse();
    for (const t of order) {
      if (t < 0) continue;
      const row = rows.get(t)!;
      const bary = new Map<string, number>();
      for (const n of row) {
        const around = neighbours.get(n.id) ?? [];
        bary.set(n.id, around.length ? around.reduce((s, m) => s + (slot.get(m) ?? 0.5), 0) / around.length : slot.get(n.id)!);
      }
      row.sort((a, b) => bary.get(a.id)! - bary.get(b.id)! || a.id.localeCompare(b.id));
      assign(row);
    }
  }

  // Wrap each row into lines. Big graphs need wider lines than the viewport, or the picture
  // becomes a tall column: choose the width that gives the whole layout the viewport's shape,
  // i.e. solve r·w² = gaps·w + slots·WRAP_GAP for w, where r is the viewport's height/width.
  const ratio = viewport.height / Math.max(1, viewport.width);
  const slotsTotal = nodes.reduce((s, n) => s + slotWidth(n), 0);
  const gaps = Math.max(0, tiers.length - 1) * 64;
  const shaped = (gaps + Math.sqrt(gaps * gaps + 4 * ratio * slotsTotal * WRAP_GAP)) / (2 * ratio);
  const maxWidth = Math.max(420, viewport.width * 0.86, shaped);
  const scale = maxWidth / Math.max(1, viewport.width * 0.86); // >1 when zoomed out to fit
  const wrapped = new Map<number, LayerNode[][]>();
  let lineCount = 0;
  for (const t of tiers) {
    const lines: LayerNode[][] = [[]];
    let width = 0;
    for (const n of rows.get(t)!) {
      const w = slotWidth(n);
      if (width + w > maxWidth && lines[lines.length - 1].length) {
        lines.push([]);
        width = 0;
      }
      lines[lines.length - 1].push(n);
      width += w;
    }
    wrapped.set(t, lines);
    lineCount += lines.length;
  }
  // Spread tiers over the viewport's height (less the space wrapped lines need).
  const free = viewport.height * scale * 0.84 - (lineCount - tiers.length) * WRAP_GAP;
  const tierGap = Math.max(64, Math.min(180 * scale, free / Math.max(1, tiers.length - 1)));

  const positions = new Map<string, { x: number; y: number }>();
  const bands: Band[] = [];
  let y = 0;
  for (const t of tiers) {
    const lines = wrapped.get(t)!;
    const top = y + (lines.length - 1) * WRAP_GAP;
    let left = Infinity;
    lines.forEach((line, li) => {
      const lineWidth = line.reduce((s, n) => s + slotWidth(n), 0);
      // Alternate wrapped lines shift by half a slot so their edges stay distinguishable.
      let x = -lineWidth / 2 + (li % 2 === 1 ? SLOT_PAD : 0);
      for (const n of line) {
        const w = slotWidth(n);
        const cx = x + SLOT_PAD / 2 + n.size;
        positions.set(n.id, { x: cx, y: top - li * WRAP_GAP });
        left = Math.min(left, cx - n.size);
        x += w;
      }
    });
    const half = Math.min(tierGap, 120) / 2;
    bands.push({ tier: t, top: top + half, bottom: y - half, left: Number.isFinite(left) ? left : 0, count: rows.get(t)!.length });
    y = top + tierGap;
  }
  return { positions, bands, width: maxWidth };
}

/** How a band should be described to a person. */
export function bandLabel(tier: number, tiers: number): string {
  if (tier < 0) return "Unconnected";
  if (tiers <= 1) return "All";
  if (tier === 0) return "Foundations";
  if (tier === tiers - 1) return "Entry points";
  return `Tier ${tier}`;
}
