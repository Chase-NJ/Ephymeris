import type { TaskDiagnostic, TaskEntry } from "@/lib/ws/protocol";

import { setBinding, type SpineDefinition } from "./spine";
import { bindShared, roleScopes, sharedChannel } from "./spineWords";

/**
 * The guided first spine task (`TASKS.md#the-guide`): its steps, which of the
 * preview's problems each one shows, and the stimulus roles it asks per trial
 * type.
 *
 * THE GUIDE JUDGES NOTHING. Every step edits the one unsaved document with the
 * editor's own functions, and every problem it shows is the preview's, filed
 * under the step that can fix it. Next is never held: the guide is skippable at
 * every step, so Simulate and Save are where whatever is left is said.
 */

export const GUIDE_STEPS = ["paradigm", "names", "roles", "answers", "timings", "session", "simulate", "save"] as const;
export type GuideStep = (typeof GUIDE_STEPS)[number];

/** Each step's title and the one line under it. */
export const STEP_WORDS: Record<GuideStep, { title: string; help: string }> = {
  paradigm: { title: "Choose a paradigm", help: "A paradigm brings the steps of a trial, its trial types and what each answer means. Everything can be changed later." },
  names: { title: "Name the trial types", help: "Each trial type is one kind of trial the session draws, such as Odor 1 or CS+. Its name titles every readout." },
  roles: {
    title: "Pick the channel for each role",
    help: "A role is a part in the trial: the port, the sample, a well, the line that pays. A channel is the line on this rig that plays it. Most roles are the same channel in every trial type; the stimulus is usually one per trial type.",
  },
  answers: { title: "Say what each answer means", help: "For each trial type, what every response (and no response) counts as, and whether it pays." },
  timings: { title: "The timings that matter", help: "How long each step of the trial lasts. The rest keep the paradigm's values." },
  session: { title: "The shape of the session", help: "How the trial types are drawn and when the session ends." },
  simulate: { title: "Check it against a pretend animal", help: "Run the session against an animal that always answers correctly, and one that answers at random, before any animal sees it." },
  save: { title: "Save", help: "Saving writes the task and the sketch a box flashes. It can be opened and changed in the editor at any time." },
};

/** Offered on `/task/new` while the machine has no saved spine task: read off the task list, never a stored preference. */
export function offerGuide(tasks: readonly Pick<TaskEntry, "spine">[]): boolean {
  return !tasks.some((t) => t.spine);
}

export function stepIndex(step: GuideStep): number {
  return GUIDE_STEPS.indexOf(step);
}

/** The step after `step`, or null after the last. */
export function nextStep(step: GuideStep): GuideStep | null {
  return GUIDE_STEPS[stepIndex(step) + 1] ?? null;
}

/** The step before `step`, or null before the first. */
export function previousStep(step: GuideStep): GuideStep | null {
  const at = stepIndex(step);
  return at > 0 ? GUIDE_STEPS[at - 1]! : null;
}

/** The codes each step files, by what it lets the user change (`TASKS.md#spine-diagnostics`). */
const STEP_CODES: Partial<Record<GuideStep, readonly string[]>> = {
  names: ["SPN108"],
  roles: ["SPN101", "SPN102", "SPN103", "SPN107"],
  answers: ["SPN109", "SPN112"],
};

/** The step a problem is filed under, the first that can show it. */
function stepOf(d: TaskDiagnostic): GuideStep {
  for (const step of ["names", "roles", "answers"] as const) if (STEP_CODES[step]!.includes(d.code)) return step;
  if (d.target.kind === "phase") return "timings";
  if (d.target.kind === "block" || d.target.kind === "session") return "session";
  // Everything else is about the rig and its codes (the strobe vocabulary, the
  // RAM, a role, the task as a whole): the wiring step, where the Rig and
  // Strobes links sit, so nothing waits unseen until Simulate.
  return "roles";
}

/**
 * The preview's problems a step shows: names, wiring and answers by code;
 * timings by the phase they sit on; the session by its blocks and cap; the
 * rest with the wiring. Simulate and Save show every one, since the session
 * cannot run while any is left. The paradigm step shows none: nothing is
 * chosen yet.
 */
export function stepDiagnostics(step: GuideStep, diagnostics: readonly TaskDiagnostic[]): TaskDiagnostic[] {
  if (step === "paradigm") return [];
  if (step === "simulate" || step === "save") return [...diagnostics];
  return diagnostics.filter((d) => stepOf(d) === step);
}

/** The roles asked per trial type when a paradigm is picked: its stimulus, and any role its trial types already bind differently. */
export function initialPerType(def: SpineDefinition): string[] {
  const scopes = roleScopes(def);
  return [...new Set([...stimulusRoles(def), ...def.slots.filter((s) => scopes[s.id] === "per-type").map((s) => s.id)])];
}

/**
 * The roles the guide asks per trial type at first: the stimulus. For each
 * Present, the outputs the step after it turns off; when that is several, the
 * ones already on before it (primed, as the lab's full trial primes the sample),
 * if any. With two or more Presents, a role every Present turns on is routing
 * (the vacuum), never a stimulus. Any role can then be flipped either way.
 */
export function stimulusRoles(def: SpineDefinition): string[] {
  const spine = def.spine;
  const presents = spine.flatMap((p, at) => (p.phase === "present" ? [at] : []));
  const everyPresent =
    presents.length >= 2
      ? new Set((spine[presents[0]!]!.outputs ?? []).filter((o) => presents.every((at) => spine[at]!.outputs?.includes(o))))
      : new Set<string>();
  const out: string[] = [];
  for (const at of presents) {
    const outputs = spine[at]!.outputs ?? [];
    const after = new Set(spine[at + 1]?.outputs ?? []);
    const before = new Set(at > 0 ? (spine[at - 1]!.outputs ?? []) : []);
    let candidates = outputs.filter((o) => !after.has(o) && !everyPresent.has(o));
    if (candidates.length > 1) {
      const primed = candidates.filter((o) => before.has(o));
      if (primed.length > 0) candidates = primed;
    }
    for (const role of candidates) if (!out.includes(role)) out.push(role);
  }
  return out.filter((role) => def.slots.some((s) => s.id === role));
}

/**
 * Make `role` shared or per trial type. Shared binds every trial type to the
 * channel of the first trial type that binds it; per type keeps each trial type's own binding.
 */
export function setScope(perType: readonly string[], def: SpineDefinition, role: string, wantPerType: boolean): { perType: string[]; def: SpineDefinition } {
  if (wantPerType) return { perType: perType.includes(role) ? [...perType] : [...perType, role], def };
  return { perType: perType.filter((r) => r !== role), def: bindShared(def, role, sharedChannel(def, role)) };
}

/** Bind a role: every trial type at once when it is shared, or trial type `row` alone. */
export function bindRole(def: SpineDefinition, role: string, channel: string, row: number | null): SpineDefinition {
  return row === null ? bindShared(def, role, channel) : setBinding(def, row, role, channel);
}
