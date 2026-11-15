import type { SpinePhase } from "./spine";

/**
 * How the spine editor names and lays out the palette (`TASKS.md#the-spine-editor`).
 *
 * Words and controls only. Which phases, outcome classes and selections exist
 * comes from the sidecar (`tasks.spinePalette`); whether a phase's fields are
 * right is the sidecar's diagnostics. This is what each control is called, and
 * which of a phase's fields its panel offers, read off the palette's table in
 * `TASKS.md#what-a-spine-task-holds`, in the user's words: a Wait "waits for"
 * an input and "gives up after" a timeout; a penalty is "after an early end".
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

/** What each phase kind is for, in one line: the palette's help. */
export const PHASE_HELP: Record<string, string> = {
  wait: "Waits for an input to be entered or left, with an optional limit",
  hold: "The input must stay held this long; letting go ends the trial",
  present: "A stimulus: lines on for a set time, optionally held at a port",
  delay: "A set time with nothing asked, optionally held at a port",
  response: "The answer: watches the response inputs for a set time; each trial type says what each answer means",
  counter: "Counts presses to N, fixed, drawn or progressive",
  outcome: "Pays the reward line and marks the trial, then waits",
  iti: "Between trials. Always last",
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

/**
 * Where a field sits in the phase panel: what the phase does, what ends it
 * early (a timeout, an abort, a limit), and what follows an early end (a
 * penalty in place of the ITI). The split is what keeps a timeout, which is
 * the phase's own limit, apart from a penalty, which replaces the ITI after
 * that exit (`GLOSSARY.md#penalty`).
 */
export type FieldGroup = "does" | "ends" | "after";

export const FIELD_GROUPS: ReadonlyArray<{ group: FieldGroup; label: string; help: string }> = [
  { group: "does", label: "What it does", help: "" },
  { group: "ends", label: "What ends it early", help: "A timeout or a limit is this step's own clock; an abort is an input the animal lets go or enters. Each ends the trial and marks it." },
  { group: "after", label: "After an early end", help: "A penalty is how long the box waits before the next trial, in place of the ITI." },
];

export interface PhaseField {
  key: keyof SpinePhase;
  label: string;
  kind: FieldKind;
  group: FieldGroup;
  /** Left out of the phase until the operator adds it. */
  optional?: boolean;
}

/** Every phase's fields after its own: what any phase may name. A new plain
 *  field of the palette is one line here. */
const COMMON: PhaseField[] = [
  { key: "outputs", label: "On during it", kind: "outputs", group: "does" },
  // Recorded and counted, never acted on: a rate window's counts. Only an
  // input a phase lists here is strobed while it runs (`TASKS.md#the-runner`).
  { key: "watch", label: "Recorded here", kind: "inputs", group: "does", optional: true },
];

const AFTER_EDGE: PhaseField[] = [
  { key: "abortOnRelease", label: "Aborts if let go", kind: "input", group: "ends", optional: true },
  { key: "abortOnEnter", label: "Aborts on entry to", kind: "input", group: "ends", optional: true },
];

export const PHASE_FIELDS: Record<string, PhaseField[]> = {
  wait: [
    { key: "on", label: "Waits for", kind: "input", group: "does" },
    { key: "edge", label: "Until it is", kind: "edge", group: "does", optional: true },
    { key: "timeoutMs", label: "Gives up after", kind: "ms", group: "ends", optional: true },
    { key: "penaltyMs", label: "Penalty after giving up", kind: "ms", group: "after", optional: true },
    { key: "escalateMs", label: "Penalty grows by, per trial without a poke", kind: "ms", group: "after", optional: true },
    { key: "escalateMaxMs", label: "Penalty at most", kind: "ms", group: "after", optional: true },
  ],
  hold: [
    { key: "on", label: "Holds", kind: "input", group: "does" },
    { key: "ms", label: "For", kind: "ms", group: "does" },
    { key: "penaltyMs", label: "Penalty if let go early", kind: "ms", group: "after", optional: true },
  ],
  present: [
    { key: "ms", label: "Lasts", kind: "ms", group: "does" },
    ...AFTER_EDGE,
    { key: "penaltyMs", label: "Penalty after an abort", kind: "ms", group: "after", optional: true },
  ],
  delay: [
    { key: "ms", label: "Lasts", kind: "ms", group: "does" },
    ...AFTER_EDGE,
    { key: "penaltyMs", label: "Penalty after an abort", kind: "ms", group: "after", optional: true },
  ],
  response: [
    { key: "responses", label: "Answers at", kind: "inputs", group: "does" },
    { key: "ms", label: "Time to answer", kind: "ms", group: "does" },
    { key: "holdMs", label: "Answer held for", kind: "ms", group: "does", optional: true },
    { key: "brokenPenaltyMs", label: "Penalty if the answer is let go early", kind: "ms", group: "after", optional: true },
  ],
  counter: [
    { key: "on", label: "Counts presses of", kind: "input", group: "does" },
    { key: "count", label: "N (or lowest N)", kind: "count", group: "does", optional: true },
    { key: "countMax", label: "Highest N (drawn)", kind: "count", group: "does", optional: true },
    { key: "ratios", label: "Progressive ratios", kind: "ints", group: "does", optional: true },
    { key: "timeoutMs", label: "Time limit", kind: "ms", group: "ends", optional: true },
    { key: "endsSession", label: "The limit ends the session", kind: "bool", group: "ends", optional: true },
    { key: "penaltyMs", label: "Penalty after the limit", kind: "ms", group: "after", optional: true },
  ],
  outcome: [
    { key: "line", label: "Pays from", kind: "line", group: "does", optional: true },
    { key: "ms", label: "Then waits", kind: "ms", group: "does" },
    { key: "awaitExit", label: "Waits for the paid well to be left", kind: "bool", group: "does", optional: true },
  ],
  iti: [{ key: "ms", label: "Between trials", kind: "ms", group: "does" }],
};

export function phaseFields(kind: string): PhaseField[] {
  return [...(PHASE_FIELDS[kind] ?? []), ...COMMON];
}

/** One line on what a phase watches and how long it lasts, in the model's
 *  own terms: slot ids and milliseconds. The diagram captions phases in words
 *  instead (`spineWords.phaseCaption`); this is the compact form. */
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
