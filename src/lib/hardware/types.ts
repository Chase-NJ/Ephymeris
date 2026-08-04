import type { CommandResultMap } from "@/lib/ws/protocol";

/**
 * The rig wiring document.
 *
 * Loose in the same way `SpecDocument` is, and for the same reason: the sidecar
 * owns `schema/rig_hardware.v1.json` and pinning the full shape here would be a
 * second schema that drifts. What is declared is the part the editor reads
 * structurally — a channel's kind, a pin's index — because those are the fields
 * the board map lays out and the rail edits.
 */
export interface RigChannel {
  kind: string;
  label?: string;
  well?: string;
  port_slot?: number;
  rationale?: string;
}

export interface RigPin {
  index: number;
  watch_bit?: number;
  note?: string;
}

export interface RigDocument {
  rig_version: number;
  derived_from?: string;
  board?: string;
  pin_range?: { min: number; max: number };
  channels: Record<string, RigChannel>;
  pins: Record<string, RigPin>;
  [key: string]: unknown;
}

export type RigProblem = CommandResultMap["hardware.get"]["problems"][number];
export type RigStatus = CommandResultMap["hardware.get"]["status"];
export type RigImpact = CommandResultMap["hardware.preview"]["breaks"][number];

/** The six kinds `channels.v1.json` declares, in the order the rail lists them. */
export const KINDS = [
  "engagement",
  "response",
  "emitter",
  "reward",
  "cue",
  "vacuum",
] as const;

/**
 * One colour per kind, so a glance at the board says what a pin does.
 *
 * Drawn from the chart series rather than invented, which keeps the palette to
 * the six tokens `docs/dashboard.md` §1.2 fixes. `engagement` takes pulsar and
 * `response` takes ion because those two are what an animal touches — the
 * accent and the success colour, used for the thing the task is actually about.
 */
export const KIND_COLOR: Record<string, string> = {
  engagement: "var(--color-pulsar)",
  response: "var(--color-ion)",
  emitter: "var(--color-series-5)",
  reward: "var(--color-series-3)",
  cue: "var(--color-series-4)",
  vacuum: "var(--color-series-6)",
};

export function kindColor(kind: string | undefined): string {
  return (kind && KIND_COLOR[kind]) || "var(--color-static)";
}
