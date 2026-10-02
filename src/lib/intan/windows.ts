import { WebviewWindow } from "@tauri-apps/api/webviewWindow";

import type { ScopeKind } from "./types";

/**
 * Open one recording pop-up as its own OS window (`RECORDING.md#live-windows`).
 *
 * Real windows rather than panels inside Mission Control, because that is how
 * they are used: dragged to a second monitor beside RHX and left open across
 * boxes while the main window goes on showing the session.
 *
 * The window is this same bundle at `#/scope/<kind>`; `main.tsx` sees the hash
 * and mounts the slim tree. Everything the view needs rides in the query,
 * because the new window shares no memory with this one — including the PSTH's
 * trigger vocabulary, which only the main window (holding the task profile)
 * knows.
 */

export interface ScopeTrigger {
  code: number;
  name: string;
}

const SIZES: Record<ScopeKind, { width: number; height: number }> = {
  spikescope: { width: 520, height: 470 },
  psth: { width: 560, height: 560 },
  isi: { width: 520, height: 420 },
  probemap: { width: 420, height: 640 },
};

const TITLES: Record<ScopeKind, string> = {
  spikescope: "Spike Scope",
  psth: "PSTH",
  isi: "ISI",
  probemap: "Probe Map",
};

let opened = 0;

export function scopeTitle(kind: ScopeKind, box: number, animal?: string | null): string {
  return `${TITLES[kind]} · Box ${box}${animal ? ` · ${animal}` : ""}`;
}

export function openScopeWindow(
  kind: ScopeKind,
  box: number,
  options: { animal?: string | null; channel?: string | null; triggers?: ScopeTrigger[] } = {},
): void {
  const query = new URLSearchParams({ box: String(box) });
  if (options.animal) query.set("animal", options.animal);
  if (options.channel) query.set("channel", options.channel);
  if (options.triggers?.length) {
    query.set("triggers", options.triggers.map((t) => `${t.code}:${t.name}`).join(","));
  }

  // Labels must be unique among LIVE windows and match `scope-*`, which is what
  // `capabilities/scope.json` grants to. A counter rather than the box number:
  // two SpikeScopes on one box, on two channels, is an ordinary thing to want.
  opened += 1;
  const label = `scope-${kind}-${box}-${Date.now().toString(36)}${opened}`;
  const size = SIZES[kind];
  const stagger = ((opened - 1) % 6) * 28;

  const view = new WebviewWindow(label, {
    url: `index.html#/scope/${kind}?${query.toString()}`,
    title: scopeTitle(kind, box, options.animal),
    width: size.width,
    height: size.height,
    minWidth: 360,
    minHeight: 300,
    x: 120 + stagger,
    y: 120 + stagger,
    decorations: false,
    // The app's Void, so the frame does not flash white before the bundle paints.
    backgroundColor: "#0B0B10",
  });
  void view.once("tauri://error", (event) => {
    console.error(`could not open the ${kind} window`, event.payload);
  });
}
