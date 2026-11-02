import type { SpinePhase } from "./spine";

/**
 * How the spine editor names and lays out the palette (`TASKS.md#the-spine-editor`).
 *
 * Words and controls only. Which phases, outcome classes and selections exist
 * comes from the sidecar (`tasks.spinePalette`); whether a phase's fields are
 * right is the sidecar's diagnostics. This is what each control is called, and
 * which of a phase's fields its panel offers, read off the palette's table in
 * `TASKS.md#what-a-spine-task-holds`.
 */

export const PHASE_LABEL: Record<string, string> = {
  wait: "Wait",
  hold: "Hold",
  present: "Present",
  delay: "Delay",
  response: "Response window",
  counter: "Counter",
  outcome: "Outcome",
  iti: "ITI",
};

export const SLOT_TYPES = [
  { value: "digital_in", label: "input" },
  { value: "digital_out", label: "output" },
  { value: "digital_out:train", label: "pulse train" },
  { value: "pwm_out", label: "PWM" },
  { value: "tone_out", label: "tone" },
] as const;

/** A slot's type, in the words `SLOT_TYPES` uses. */
export function slotTypeLabel(type: string, mode?: string | null): string {
  const key = mode ? `${type}:${mode}` : type;
  return SLOT_TYPES.find((t) => t.value === key)?.label ?? key;
}

/** An outcome class as a person reads it: `wrong_response` → "wrong response". */
export function classLabel(outcome: string): string {
  return outcome.replace(/_/g, " ");
}

/**
 * The control a phase field takes:
 *   input    one input slot          inputs   several input slots
 *   outputs  several output slots    line     one level output slot
 *   ms       a duration              count    a whole number
 *   ints     a list of whole numbers bool     on or off
 *   edge     `enter` or `exit`
 */
export type FieldKind = "input" | "inputs" | "outputs" | "line" | "ms" | "count" | "ints" | "bool" | "edge";

export interface PhaseField {
  key: keyof SpinePhase;
  label: string;
  kind: FieldKind;
  /** Left out of the phase until the operator adds it. */
  optional?: boolean;
}

/** Every phase's fields after its own: what any phase may name. A new plain
 *  field of the palette is one line here. */
const COMMON: PhaseField[] = [
  { key: "outputs", label: "Outputs on", kind: "outputs" },
  // Counted and strobed, never acted on: a rate window's counts. Its label keeps
  // it apart from the Response window's "Watches", which a response moves.
  { key: "watch", label: "Counts, never acts on", kind: "inputs", optional: true },
];

const AFTER_EDGE: PhaseField[] = [
  { key: "abortOnRelease", label: "Abort on release of", kind: "input", optional: true },
  { key: "abortOnEnter", label: "Abort on entry to", kind: "input", optional: true },
];

export const PHASE_FIELDS: Record<string, PhaseField[]> = {
  wait: [
    { key: "on", label: "Waits on", kind: "input" },
    { key: "edge", label: "Edge", kind: "edge", optional: true },
    { key: "timeoutMs", label: "Timeout", kind: "ms", optional: true },
  ],
  hold: [
    { key: "on", label: "Holds", kind: "input" },
    { key: "ms", label: "For", kind: "ms" },
  ],
  present: [{ key: "ms", label: "Lasts", kind: "ms" }, ...AFTER_EDGE],
  delay: [{ key: "ms", label: "Lasts", kind: "ms" }, ...AFTER_EDGE],
  response: [
    { key: "responses", label: "Watches", kind: "inputs" },
    { key: "ms", label: "Window", kind: "ms" },
    { key: "holdMs", label: "Hold a response for", kind: "ms", optional: true },
  ],
  counter: [
    { key: "on", label: "Counts", kind: "input" },
    { key: "count", label: "N (or lowest N)", kind: "count", optional: true },
    { key: "countMax", label: "Highest N (drawn)", kind: "count", optional: true },
    { key: "ratios", label: "Progressive ratios", kind: "ints", optional: true },
    { key: "timeoutMs", label: "Time limit", kind: "ms", optional: true },
    { key: "endsSession", label: "Limit ends the session", kind: "bool", optional: true },
  ],
  outcome: [
    { key: "line", label: "Reward line", kind: "line", optional: true },
    { key: "ms", label: "Then waits", kind: "ms" },
  ],
  iti: [{ key: "ms", label: "Lasts", kind: "ms" }],
};

export function phaseFields(kind: string): PhaseField[] {
  return [...(PHASE_FIELDS[kind] ?? []), ...COMMON];
}

/** One line on what a phase watches and how long it lasts, as the diagram
 *  captions it. Read off the phase as the preview's snapshot holds it. */
export function phaseDetail(phase: SpinePhase): string {
  const parts: string[] = [];
  if (phase.on) parts.push(phase.edge === "exit" ? `${phase.on} exit` : phase.on);
  if (phase.responses?.length) parts.push(phase.responses.join(" · "));
  if (phase.count !== undefined) {
    parts.push(phase.countMax !== undefined ? `N ${phase.count}–${phase.countMax}` : `N ${phase.count}`);
  }
  if (phase.ratios?.length) parts.push(`PR ${phase.ratios.length}`);
  if (phase.line) parts.push(`pays ${phase.line}`);
  if (phase.ms !== undefined) parts.push(`${phase.ms} ms`);
  if (phase.timeoutMs !== undefined) parts.push(`≤ ${phase.timeoutMs} ms`);
  if (phase.watch?.length) parts.push(`counts ${phase.watch.join(" · ")}`);
  return parts.join(" · ");
}
