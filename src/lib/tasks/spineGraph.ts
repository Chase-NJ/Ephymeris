/**
 * A spine task's trial flow, read from its profile's snapshot alone
 * (`ARCHITECTURE.md#live-session-views`).
 *
 * A spine task is an ordered list of phases (`TASKS.md#what-a-spine-task-holds`),
 * so its diagram is that list, left to right, with the ITI leading back to the
 * start. Mission Control's live token sits on the phase **the sidecar reports**
 * (`session.replay`'s `phase`, an index into this same list): nothing here, and
 * nothing that draws it, reads a strobe or a code's name, and nothing predicts
 * where the board goes next (`ARCHITECTURE.md#overview`).
 *
 * Pure: no React, no store.
 */

import type { TaskProfile } from "@/lib/ws/protocol";

/** One phase of the spine, in spine order. */
export interface SpinePhase {
  /** Its index in the snapshot's `spine`: what `LiveReplay.phase` names. */
  index: number;
  /** The phase kind as the definition writes it (`wait`, `response`, …). */
  kind: string;
  /** What the operator reads. */
  label: string;
  /** One line of detail: its duration, or what it waits on. */
  detail: string | null;
}

export interface SpineGraph {
  phases: SpinePhase[];
  /** The task's rows (trial types), id → name, in its order. */
  rows: { id: string; name: string }[];
}

const LABELS: Record<string, string> = {
  wait: "Wait",
  hold: "Hold",
  present: "Present",
  delay: "Delay",
  response: "Response window",
  counter: "Counter",
  outcome: "Outcome",
  iti: "ITI",
};

/** The spine of `profile`, or null for a profile that carries none. */
export function spineGraph(profile: TaskProfile | null | undefined): SpineGraph | null {
  const spine = profile?.spine;
  if (!spine || !Array.isArray(spine.spine)) return null;
  const phases = (spine.spine as unknown[]).map((raw, index): SpinePhase => {
    const phase = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
    const kind = typeof phase.phase === "string" ? phase.phase : "?";
    return { index, kind, label: LABELS[kind] ?? kind, detail: detailOf(phase) };
  });
  const rows = (Array.isArray(spine.rows) ? (spine.rows as unknown[]) : []).flatMap((raw) => {
    if (!raw || typeof raw !== "object") return [];
    const row = raw as Record<string, unknown>;
    if (typeof row.id !== "string") return [];
    return [{ id: row.id, name: typeof row.name === "string" && row.name ? row.name : row.id }];
  });
  return { phases, rows };
}

function detailOf(phase: Record<string, unknown>): string | null {
  const parts: string[] = [];
  if (typeof phase.on === "string") parts.push(`on ${phase.on}`);
  if (Array.isArray(phase.responses)) parts.push(`watching ${phase.responses.join(", ")}`);
  if (typeof phase.ms === "number") parts.push(`${phase.ms} ms`);
  if (typeof phase.timeoutMs === "number") parts.push(`times out at ${phase.timeoutMs} ms`);
  if (typeof phase.count === "number") {
    parts.push(
      typeof phase.countMax === "number"
        ? `${phase.count}–${phase.countMax} presses`
        : `${phase.count} presses`,
    );
  }
  if (Array.isArray(phase.ratios)) parts.push("progressive ratio");
  return parts.length ? parts.join(" · ") : null;
}

/** The name of a row id, or the id itself when the spine does not list it. */
export function rowName(graph: SpineGraph, row: string | null): string | null {
  if (row === null) return null;
  return graph.rows.find((r) => r.id === row)?.name ?? row;
}
