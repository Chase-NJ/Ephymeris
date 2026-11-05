import { KINDS, type RigDocument } from "@/lib/hardware/types";

import type { MapEntry, SpineDefinition, SpinePhase, SpineRow } from "./spine";

/**
 * The spine editor in the user's words (`TASKS.md#the-spine-editor`): a
 * neuroscientist designs a task in trial types, responses, what counts as
 * correct and the shape of the session, so this says the model back in those
 * terms. A channel by its Rig-tab label, a contingency map as a sentence per
 * response, the note an outcome class needs where the model surprises people,
 * what each early exit of a phase is scored as, and a phase's caption.
 *
 * WORDS ONLY. Nothing here validates: what a slot can bind, whether a map is
 * complete and every problem are the preview's (`tasks.preview`). The rig
 * document is read for its labels and kinds, the way the trial-table editor
 * reads them (`channelLabel`), never for what a slot may bind.
 */

/** One channel as the pickers offer it: its name on the wire, its Rig-tab label, and its kind. */
export interface ChannelChoice {
  name: string;
  label: string;
  kind: string;
}

/** The kinds as the pickers group them, in the order the Rig page lists them. */
const KIND_WORDS: Record<string, string> = {
  engagement: "ports",
  response: "response ports",
  emitter: "stimulus lines",
  reward: "reward lines",
  cue: "cues",
  vacuum: "vacuum",
  sync: "sync",
};

/** What this rig calls a channel: its Rig-tab label, else its name in words. */
export function channelWord(name: string, rig: RigDocument | null): string {
  const label = rig?.channels?.[name]?.label?.trim();
  return label || name.replace(/_/g, " ");
}

/** The channels the preview offers a slot, each with its label and kind. */
export function channelChoices(names: readonly string[], rig: RigDocument | null): ChannelChoice[] {
  return names.map((name) => ({ name, label: channelWord(name, rig), kind: rig?.channels?.[name]?.kind ?? "" }));
}

export interface ChannelGroup {
  kind: string;
  label: string;
  choices: ChannelChoice[];
}

/** The choices grouped by kind, kinds in the Rig page's order, unknown kinds last. */
export function channelGroups(choices: readonly ChannelChoice[]): ChannelGroup[] {
  const order = [...KINDS, ""] as readonly string[];
  const groups: ChannelGroup[] = [];
  for (const kind of order) {
    const mine = choices.filter((c) => (order.includes(c.kind) ? c.kind : "") === kind);
    if (mine.length) groups.push({ kind, label: KIND_WORDS[kind] ?? "other channels", choices: mine });
  }
  return groups;
}

/** A duration as a person says it: 200 ms, 1.5 s, 20 s, 2 min. */
export function msWord(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) {
    const s = ms / 1000;
    return `${Number.isInteger(s) ? s : s.toFixed(1)} s`;
  }
  const min = ms / 60_000;
  return `${Number.isInteger(min) ? min : min.toFixed(1)} min`;
}

/** An outcome class in words: `wrong_response` → "wrong response". */
export function classWord(outcome: string): string {
  return outcome.replace(/_/g, " ");
}

/** The classes P(correct) counts as a hit, and the ones it leaves out
 *  (`lowering.HIT_CLASSES`, `EXCLUDED_CLASSES`, `TASKS.md#blocks`). Words
 *  only: the scorer's own sets live in the sidecar. */
const HITS = new Set(["correct", "withheld"]);
const EXCLUDED = new Set(["abort_before_stimulus", "abort_during_sampling"]);

/**
 * The note an outcome class needs where the model surprises people, or null
 * where it says what it means. `windowed` is whether the row answers through
 * a Response window; without one an Outcome scores every trial correct.
 */
export function classNote(outcome: string, windowed = true): string | null {
  switch (outcome) {
    case "withheld":
      return "counts as a hit, like correct: not answering was the right thing";
    case "correct":
      return windowed ? null : "every trial of this type scores correct, since nothing is asked; what differs is whether it pays";
    case "abort_before_stimulus":
    case "abort_during_sampling":
      return "left out of P(correct): the trial is not counted";
    case "hold_broken":
      return "the answer was let go too soon: a miss";
    case "omission":
      return "no answer in time: a miss";
    default:
      return null;
  }
}

/** Whether P(correct) counts the class as a hit, a miss, or leaves it out. */
export function classScore(outcome: string): "hit" | "miss" | "left out" {
  if (HITS.has(outcome)) return "hit";
  if (EXCLUDED.has(outcome)) return "left out";
  return "miss";
}

/** The spine's first Present, which decides an early exit's class, or -1. */
export function firstPresent(def: SpineDefinition): number {
  return def.spine.findIndex((p) => p.phase === "present");
}

/** The spine's Response window, or -1. */
export function responseWindow(def: SpineDefinition): number {
  return def.spine.findIndex((p) => p.phase === "response");
}

export interface ExitNote {
  /** What ends the phase early, in words. */
  exit: string;
  /** The class the trial is marked, or how it is decided. */
  outcome: string;
}

/**
 * What each early end of a phase is scored as, read off the spine as
 * `TASKS.md#lowering` lays it down: an abort or a Wait's timeout before the
 * first Present is `abort_before_stimulus` (no stimulus was offered); from the
 * first Present on, an abort is `abort_during_sampling` and a Wait's timeout an
 * `omission`. Past the Outcome a trial is already marked.
 */
export function exitNotes(def: SpineDefinition, at: number): ExitNote[] {
  const phase = def.spine[at];
  if (!phase) return [];
  const outcome = def.spine.findIndex((p) => p.phase === "outcome");
  if (outcome >= 0 && at > outcome) {
    return [{ exit: "an early end here", outcome: "marks nothing: the trial was already scored at the Outcome" }];
  }
  const stimulus = firstPresent(def);
  const beforeStimulus = stimulus < 0 || at < stimulus;
  const abort = beforeStimulus ? "abort_before_stimulus" : "abort_during_sampling";
  const notes: ExitNote[] = [];
  switch (phase.phase) {
    case "wait":
      notes.push({
        exit: phase.timeoutMs !== undefined ? `no ${phase.on ?? "input"} within ${msWord(phase.timeoutMs)}` : "no timeout: it waits as long as it takes",
        outcome: phase.timeoutMs === undefined ? "" : beforeStimulus ? "abort_before_stimulus" : "omission",
      });
      break;
    case "hold":
      notes.push({ exit: `${phase.on ?? "the input"} let go before ${msWord(phase.ms ?? 0)}`, outcome: "hold_broken" });
      break;
    case "present":
    case "delay":
      if (phase.abortOnRelease) notes.push({ exit: `${phase.abortOnRelease} let go`, outcome: abort });
      if (phase.abortOnEnter) notes.push({ exit: `${phase.abortOnEnter} entered`, outcome: abort });
      break;
    case "counter":
      if (phase.timeoutMs !== undefined) {
        notes.push({
          exit: `fewer than N presses within ${msWord(phase.timeoutMs)}`,
          outcome: phase.endsSession ? "omission, and the session ends after this trial" : "omission",
        });
      }
      break;
    case "response":
      notes.push({ exit: `no answer within ${msWord(phase.ms ?? 0)}`, outcome: "each trial type's \"no answer\" line decides" });
      if (phase.holdMs !== undefined) notes.push({ exit: `an answer let go before ${msWord(phase.holdMs)}`, outcome: "hold_broken" });
      break;
    default:
      break;
  }
  return notes;
}

/** The slot's channel in a row, by its Rig-tab label, or the slot's own id while unbound. */
function slotWord(row: SpineRow, slot: string, rig: RigDocument | null): string {
  const channel = row.bind[slot];
  return channel ? channelWord(channel, rig) : slot;
}

function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export interface MapSentence {
  /** The map's key: a response slot, or `timeout`. */
  key: string;
  /** "Left well", or "No answer in 5 s". */
  subject: string;
  /** "correct, pays fluid 1, held · then a 20 s penalty", or "not mapped yet". */
  clause: string;
}

/** One map entry's clause, as `mapSentences` words it. */
export function entryClause(entry: MapEntry | undefined, row: SpineRow, window: SpinePhase | undefined, rig: RigDocument | null): string {
  if (!entry) return "not mapped yet";
  const parts = [classWord(entry.outcome)];
  if (entry.line) {
    const permille = entry.rewardPermille ?? 1000;
    parts.push(`pays ${slotWord(row, entry.line, rig)}${permille < 1000 ? ` on ${permille / 10} % of trials` : ""}`);
  }
  if (entry.hold && window?.holdMs !== undefined) parts.push(`held ${msWord(window.holdMs)}`);
  const then = entry.penaltyMs !== undefined ? ` · then a ${msWord(entry.penaltyMs)} penalty instead of the ITI` : "";
  return parts.join(", ") + then;
}

/**
 * A row's contingency map as one sentence per response, in the window's
 * order and the timeout last: "Left well → correct, pays fluid 1, held".
 * Each subject is the channel the row binds, by its Rig-tab label, so the
 * sentence reads in this rig's words; an unbound slot keeps its role's name.
 */
export function mapSentences(def: SpineDefinition, row: SpineRow, rig: RigDocument | null): MapSentence[] {
  const at = responseWindow(def);
  const window = at >= 0 ? def.spine[at] : undefined;
  if (!window) return [];
  const keys = [...(window.responses ?? []), "timeout"];
  return keys.map((key) => ({
    key,
    subject: key === "timeout" ? `No answer in ${msWord(window.ms ?? 0)}` : capital(slotWord(row, key, rig)),
    clause: entryClause(row.map?.[key], row, window, rig),
  }));
}

/** The whole map as one line: "Left well → correct, pays fluid 1 · Right well → wrong response · No answer in 5 s → omission". */
export function rowSentence(def: SpineDefinition, row: SpineRow, rig: RigDocument | null): string {
  const sentences = mapSentences(def, row, rig);
  if (sentences.length === 0) {
    const outcome = def.spine.find((p) => p.phase === "outcome");
    const line = outcome?.line ? `pays ${slotWord(row, outcome.line, rig)}` : "pays nothing";
    const permille = row.rewardPermille;
    return `No answer is asked: every trial ${line}${permille < 1000 ? ` on ${permille / 10} % of trials` : ""} and scores correct`;
  }
  return sentences.map((s) => `${s.subject} → ${s.clause}`).join(" · ");
}

/**
 * A phase's caption for the diagram, in words: what it waits for or holds,
 * what it turns on, and how long. Short, because a node is narrow; the phase
 * panel says the rest.
 */
export function phaseCaption(phase: SpinePhase): string {
  const parts: string[] = [];
  switch (phase.phase) {
    case "wait":
      parts.push(phase.on ? `until ${phase.on} ${phase.edge === "exit" ? "is left" : "is entered"}` : "until an input");
      if (phase.timeoutMs !== undefined) parts.push(`up to ${msWord(phase.timeoutMs)}`);
      break;
    case "hold":
      parts.push(phase.on ? `${phase.on} held ${msWord(phase.ms ?? 0)}` : msWord(phase.ms ?? 0));
      break;
    case "present":
      parts.push(`${phase.outputs?.length ? `${phase.outputs.join(", ")} on` : "nothing on"} · ${msWord(phase.ms ?? 0)}`);
      break;
    case "delay":
      parts.push(msWord(phase.ms ?? 0));
      if (phase.abortOnRelease) parts.push(`${phase.abortOnRelease} held`);
      break;
    case "response":
      parts.push(`answer at ${phase.responses?.length ? phase.responses.join(" or ") : "nothing"} · ${msWord(phase.ms ?? 0)}`);
      if (phase.holdMs !== undefined) parts.push(`held ${msWord(phase.holdMs)}`);
      break;
    case "counter":
      parts.push(
        phase.ratios?.length
          ? `${phase.on ?? "presses"} · progressive ratio`
          : `${phase.countMax !== undefined ? `${phase.count ?? 1}–${phase.countMax}` : (phase.count ?? 1)} × ${phase.on ?? "presses"}`,
      );
      if (phase.timeoutMs !== undefined) parts.push(`within ${msWord(phase.timeoutMs)}`);
      break;
    case "outcome":
      parts.push(phase.line ? `pays ${phase.line}` : "pays as the trial type says");
      if ((phase.ms ?? 0) > 0) parts.push(`then ${msWord(phase.ms ?? 0)}`);
      break;
    case "iti":
      parts.push(`${msWord(phase.ms ?? 0)} between trials`);
      break;
    default:
      if (phase.ms !== undefined) parts.push(msWord(phase.ms));
  }
  if (phase.watch?.length) parts.push(`records ${phase.watch.join(", ")}`);
  return parts.join(" · ");
}

/** A seed's shape, for its card: "8 steps · 2 trial types · 7 roles". */
export function seedShapeWords(def: SpineDefinition): string {
  const n = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
  return `${n(def.spine.length, "step")} · ${n(def.rows.length, "trial type")} · ${n(def.slots.length, "role")}`;
}

export type RoleScope = "shared" | "per-type";

/**
 * Whether a role is the same wire in every trial type, or one each: what the
 * guide asks once and what it asks per trial type. A role the rows already
 * bind differently is per type. Otherwise an output that only Present phases
 * turn on is the stimulus, so per type; everything else (the port, the
 * light, the wells, the reward lines) is shared.
 */
export function roleScopes(def: SpineDefinition): Record<string, RoleScope> {
  const scopes: Record<string, RoleScope> = {};
  for (const slot of def.slots) {
    const bound = new Set(def.rows.map((r) => r.bind[slot.id]).filter((c): c is string => c !== undefined));
    if (bound.size > 1) {
      scopes[slot.id] = "per-type";
      continue;
    }
    const output = slot.type !== "digital_in";
    const users = def.spine.filter((p) => p.outputs?.includes(slot.id) || p.line === slot.id);
    const onlyPresents = users.length > 0 && users.every((p) => p.phase === "present" && p.outputs?.includes(slot.id));
    const paysSomewhere = def.rows.some((r) => Object.values(r.map ?? {}).some((e) => e.line === slot.id));
    scopes[slot.id] = output && onlyPresents && !paysSomewhere ? "per-type" : "shared";
  }
  return scopes;
}

export interface TimingField {
  /** The phase's index. */
  at: number;
  key: "ms" | "timeoutMs" | "holdMs";
  /** "Hold the poke for", "Time to answer". */
  label: string;
}

/**
 * The timings a first task is tuned by, in words, read off the spine's shape:
 * each timed phase's duration, a Wait's or Counter's limit and a window's hold.
 */
export function timingFields(def: SpineDefinition): TimingField[] {
  const fields: TimingField[] = [];
  const stimulus = firstPresent(def);
  let presents = 0;
  def.spine.forEach((phase, at) => {
    switch (phase.phase) {
      case "wait":
        if (phase.timeoutMs !== undefined) fields.push({ at, key: "timeoutMs", label: `Give up waiting for ${phase.on ?? "the input"} after` });
        break;
      case "hold":
        fields.push({ at, key: "ms", label: `Hold ${phase.on ?? "the input"} for` });
        break;
      case "present":
        presents += 1;
        fields.push({ at, key: "ms", label: presents === 1 ? "Stimulus lasts" : `Stimulus ${presents} lasts` });
        break;
      case "delay":
        fields.push({
          at,
          key: "ms",
          label: stimulus < 0 || at < stimulus ? (phase.abortOnRelease ? "Hold at the port before the stimulus for" : "Delay before the trial") : "Delay after the stimulus",
        });
        break;
      case "response":
        fields.push({ at, key: "ms", label: "Time to answer" });
        if (phase.holdMs !== undefined) fields.push({ at, key: "holdMs", label: "Hold the answer for" });
        break;
      case "counter":
        if (phase.timeoutMs !== undefined) fields.push({ at, key: "timeoutMs", label: "Time limit for the presses" });
        break;
      case "outcome":
        if ((phase.ms ?? 0) > 0 || phase.line) fields.push({ at, key: "ms", label: "After the outcome, wait" });
        break;
      case "iti":
        fields.push({ at, key: "ms", label: "Between trials" });
        break;
      default:
        if (phase.ms !== undefined) fields.push({ at, key: "ms", label: `${phase.phase} lasts` });
    }
  });
  return fields;
}
