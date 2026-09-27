// Live updates: index changes (coalesced) and the agent's activity trail.
import type { App } from "./app";
import type { Animator } from "./renderer";
import { OFFLINE_MESSAGE } from "./data";
import type { ActivityEvent, IndexEvent } from "./types";
import { $, plural, toast } from "./ui";

const COALESCE_MS = 350;

export function bindLive(app: App, animator: Animator): void {
  let pending: IndexEvent | null = null;
  let timer: number | undefined;

  const flush = () => {
    const e = pending;
    pending = null;
    if (!e) return;
    app.invalidateDetails();
    const touched = [...e.added, ...e.changed];
    void app.load({ keepCamera: true }).then((ok) => {
      if (!ok) return;
      for (const ref of touched) {
        const id = app.mapToNode(ref);
        if (id) app.state.pulses.set(id, performance.now());
      }
      animator.kick();
      app.flashSpectrum();
      const parts = [
        e.changed.length && `${plural(e.changed.length, "change")}`,
        e.added.length && `${e.added.length} added`,
        e.removed.length && `${e.removed.length} removed`,
      ].filter(Boolean);
      toast(`Index updated · ${parts.join(", ") || "no structural changes"}`);
      if (app.state.selected) app.select(app.state.selected, { moveCamera: false });
    });
  };

  const onIndex = (e: IndexEvent) => {
    // Several edits in a burst (an agent saving files) become one reload.
    pending = pending
      ? { added: [...pending.added, ...e.added], removed: [...pending.removed, ...e.removed], changed: [...pending.changed, ...e.changed] }
      : e;
    window.clearTimeout(timer);
    timer = window.setTimeout(flush, COALESCE_MS);
  };

  const onActivity = (e: ActivityEvent) => {
    const verb: Record<string, string> = {
      context: "is reading", impact: "is checking what depends on", search: "searched for",
      locate: "looked up", module: "opened module",
    };
    $("activity").textContent = `Agent ${verb[e.op] ?? e.op} ${e.ids.slice(0, 2).join(", ")}`;
    if (!app.state.showActivity) return;
    const now = performance.now();
    for (const ref of e.ids) {
      const id = app.mapToNode(ref);
      if (id) app.state.trail.set(id, now);
    }
    app.flashSpectrum();
    animator.kick();
  };

  // A dropped stream usually reconnects within a second; only a lasting outage is reported.
  let lost: number | undefined;
  let warned = false;
  app.source.subscribe(onIndex, onActivity, (ok) => {
    $("live").classList.toggle("on", ok);
    $("live-text").textContent = app.source.live ? (ok ? "Live" : "Reconnecting") : "Static export";
    if (!app.source.live) return;
    window.clearTimeout(lost);
    if (ok) {
      if (warned) toast("Reconnected to the PRISM server.");
      warned = false;
      return;
    }
    lost = window.setTimeout(() => {
      $("live-text").textContent = "Server stopped";
      if (!warned) toast(OFFLINE_MESSAGE, true);
      warned = true;
    }, 4000);
  });
}
