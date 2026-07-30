/**
 * Presentation for the hardware utility baseline (`settings.md` §8).
 *
 * The baseline is meant to be invisible while it works, so these labels are
 * written for the moment it *doesn't*: each one says what the operator would
 * need to do next, and only `failed` is coloured as a fault. `busy` and `held`
 * are the sidecar deliberately keeping its hands off a port someone else owns,
 * which is correct behaviour and must not read as a warning.
 */

import type { UtilityBoxState } from "@/lib/ws/protocol";

export type BaselineState = UtilityBoxState["state"];

const LABELS: Record<BaselineState, string> = {
  ready: "Ready",
  restoring: "Preparing…",
  busy: "In use",
  held: "Session running",
  unavailable: "No board",
  unknown: "Not checked",
  failed: "Failed",
};

export function baselineLabel(state: BaselineState): string {
  return LABELS[state] ?? state;
}

/** The token a state's indicator takes. Only a real fault gets the error colour. */
export function baselineColor(state: BaselineState): string {
  if (state === "ready") return "var(--color-ion)";
  if (state === "restoring") return "var(--color-pulsar)";
  if (state === "failed") return "var(--color-status-error)";
  return "var(--color-static)";
}
