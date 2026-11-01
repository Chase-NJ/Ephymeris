/**
 * Presentation for the hardware utility baseline (`ARCHITECTURE.md#hardware-utility-baseline`).
 *
 * The baseline is meant to be invisible while it works, so these labels are
 * written for the moment it *doesn't*: each one says what the operator would
 * need to do next, and only `failed` is coloured as a fault. `busy`, `held` and
 * `pinned` (a sketch the operator flashed from Debug Mode, kept until they ask
 * for the baseline back)
 * are the sidecar deliberately keeping its hands off a box someone else owns,
 * which is correct behaviour and must not read as a warning.
 */

import type { ControlSetting, UtilityBoxState } from "@/lib/ws/protocol";

export type BaselineState = UtilityBoxState["state"];

const LABELS: Record<BaselineState, string> = {
  ready: "Ready",
  restoring: "Preparing…",
  busy: "In use",
  held: "Session running",
  pinned: "Holding a Debug flash",
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

/**
 * What a grid row's setting reads as now (`TASKS.md#utility-controls-and-telemetry`),
 * from the value each box's latest `STATUS` reports under the setting's `state`
 * key: one value for a single box, one per box across the rig. The board is the
 * authority, so this never assumes the last option sent took effect.
 */
export type SettingReading =
  | { kind: "none" } // no box has reported it yet
  | { kind: "mixed" } // boxes disagree
  | { kind: "value"; value: string; label: string };

export function readSetting(setting: ControlSetting, values: ReadonlyArray<string | undefined>): SettingReading {
  const reported = [...new Set(values.filter((v): v is string => v !== undefined))];
  if (reported.length === 0) return { kind: "none" };
  if (reported.length > 1) return { kind: "mixed" };
  const value = reported[0]!;
  const option = setting.options.find((o) => o.value === value);
  // A value no option offers (typed at the console) is shown as the number itself.
  return { kind: "value", value, label: option?.label ?? value };
}

/**
 * The select a setting renders as: each option keyed by its command, and the
 * current one selected. Anything that is not an option (nothing reported, boxes
 * that disagree, a value typed at the console) is a placeholder first, so the
 * select never shows an option the board is not at.
 */
export function settingChoices(
  setting: ControlSetting,
  reading: SettingReading,
): { value: string; options: { value: string; label: string }[] } {
  const options = setting.options.map((o) => ({ value: o.command, label: o.label }));
  const current =
    reading.kind === "value" ? setting.options.find((o) => o.value === reading.value) : undefined;
  if (current) return { value: current.command, options };
  const placeholder = reading.kind === "value" ? reading.label : reading.kind === "mixed" ? "mixed" : "—";
  return { value: "", options: [{ value: "", label: placeholder }, ...options] };
}
