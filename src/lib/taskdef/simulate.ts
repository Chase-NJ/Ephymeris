import type { SimulatedAnimal, TaskSimulation } from "@/lib/ws/protocol";

import type { SpineDefinition } from "./spine";

/**
 * The Simulate panel's form and labels (`TASKS.md#simulating-a-spine-task`).
 * The sidecar runs the session and scores it; this only turns the form into
 * `tasks.simulate`'s arguments and says what came back in words.
 */

export type AnimalKind = SimulatedAnimal["kind"];

/** The animals, in the order the picker offers them. */
export const ANIMALS: ReadonlyArray<{ kind: AnimalKind; label: string; help: string }> = [
  { kind: "correct", label: "Always correct", help: "Engaged, and takes whatever ends the trial in a hit: withholds on a no-go row" },
  { kind: "random", label: "Random", help: "Engaged, and answers each window at random, its timeout included" },
  { kind: "biased", label: "Biased", help: "Engaged, and takes one response this often when it can, else answers at random" },
  { kind: "silent", label: "Never responds", help: "Touches nothing: every Wait times out, or the session runs to its limit" },
];

export interface SimulateForm {
  kind: AnimalKind;
  /** A biased animal's response slot. */
  response: string;
  /** How often a biased animal takes it, in percent. */
  percent: string;
  /** Blank: a fresh seed each run. */
  seed: string;
  limitMin: string;
}

export const DEFAULT_FORM: SimulateForm = { kind: "correct", response: "", percent: "80", seed: "", limitMin: "60" };

/** `tasks.seed`'s range (`tasks/seed.py`). */
const SEED_MIN = 1;
const SEED_MAX = 2 ** 31 - 2;
const LIMIT_MAX_MIN = 24 * 60;

export interface SimulateArgs {
  animal: SimulatedAnimal;
  seed?: number;
  limitMs: number;
}

/** Every response slot a Response window lists, in spine order, each once. */
export function responsesOf(def: SpineDefinition): string[] {
  const out: string[] = [];
  for (const phase of def.spine) {
    if (phase.phase !== "response") continue;
    for (const slot of phase.responses ?? []) if (!out.includes(slot)) out.push(slot);
  }
  return out;
}

/** The form as `tasks.simulate`'s arguments, or what is wrong with it. */
export function simulateArgs(def: SpineDefinition, form: SimulateForm): { args: SimulateArgs } | { error: string } {
  const limit = Number(form.limitMin);
  if (!Number.isFinite(limit) || limit <= 0 || limit > LIMIT_MAX_MIN) {
    return { error: `The time limit is more than 0 and at most ${LIMIT_MAX_MIN} minutes.` };
  }
  const args: SimulateArgs = { animal: { kind: form.kind }, limitMs: Math.round(limit * 60_000) };
  if (form.seed.trim() !== "") {
    const seed = Number(form.seed);
    if (!Number.isInteger(seed) || seed < SEED_MIN || seed > SEED_MAX) {
      return { error: `A seed is a whole number from ${SEED_MIN} to ${SEED_MAX}.` };
    }
    args.seed = seed;
  }
  if (form.kind === "biased") {
    if (!responsesOf(def).includes(form.response)) {
      return { error: "Pick the response a biased animal favours." };
    }
    const percent = Number(form.percent);
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
      return { error: "A biased animal takes its response 0 to 100% of the time." };
    }
    args.animal = { kind: "biased", response: form.response, permille: Math.round(percent * 10) };
  }
  return { args };
}

/** What ended the simulated session, in words. */
export function endedLabel(sim: TaskSimulation): string {
  switch (sim.endedBy) {
    case "trials":
      return "ended at the session's trial cap";
    case "blocks":
      return "ended when the blocks ran out";
    case "lastTrial":
      return "ended at a last-trial state";
    case "timeLimit":
      return `ended at its ${formatMinutes(sim.limitMs)} time limit`;
  }
}

function formatMinutes(ms: number): string {
  const min = ms / 60_000;
  return `${Number.isInteger(min) ? min : min.toFixed(1)} min`;
}

/** Each block switch, numbered from trial 1 as the trial table shows it. */
export function switchLabels(sim: TaskSimulation): string[] {
  return sim.switches.map((s) => `${s.block ?? "no block"} from trial ${s.index + 1}`);
}

/** Each row no trial drew, and why it might not have been. */
export function absentLabels(sim: TaskSimulation): string[] {
  return sim.absent.map((row) => {
    const name = row.name || row.rowId;
    return row.blocks.length === 0 ? `${name}: in no block` : `${name}: never drawn in ${row.blocks.join(", ")}`;
  });
}

/** "about 23 min", from the last trial's start. */
function aboutMinutes(sim: TaskSimulation): string | null {
  const last = sim.trialTable?.trials.at(-1);
  if (!last || last.atMs === null) return null;
  const min = Math.round(last.atMs / 60_000);
  return min < 1 ? "under a minute" : `about ${min} min`;
}

/**
 * The result in plain words, before any table: how many trials and how long,
 * how they ended, each row's share right, and what ended the session. Every
 * number is the sidecar's (`TaskSimulation.replay`, `overall`, `absent`);
 * this only says them.
 */
export function verdict(sim: TaskSimulation, animal: string): string[] {
  const lines: string[] = [];
  const trials = sim.replay?.trials ?? sim.trialTable?.trials.length ?? 0;
  const span = aboutMinutes(sim);
  const counted = sim.overall?.counted ?? 0;
  const hits = sim.overall?.hits ?? 0;
  const classes = (sim.replay?.classes ?? []).filter((c) => c.n > 0);
  const rows = (sim.replay?.rows ?? []).filter((r) => r.trials > 0);
  const head = `${animal}: ${trials} trial${trials === 1 ? "" : "s"}${span ? ` in ${span}` : ""}`;
  if (trials === 0) lines.push(`${head}. Nothing ran.`);
  else if (counted > 0 && hits === counted && counted === trials) {
    const byRow = rows.map((r) => `${r.trials} ${r.name ?? r.rowId ?? "unnamed"}`).join(", ");
    lines.push(`${head}, every one right${byRow ? ` (${byRow})` : ""}.`);
  } else {
    const share = counted > 0 ? `${hits} right of ${counted} counted (${Math.round((hits / counted) * 100)} %)` : "none counted";
    const mix = classes.map((c) => `${c.n} ${c.outcomeClass.replace(/_/g, " ")}`).join(", ");
    lines.push(`${head}: ${share}${mix ? ` · ${mix}` : ""}.`);
    const perRow = rows
      .map((r) => {
        const right = r.classes.filter((c) => c.outcomeClass === "correct" || c.outcomeClass === "withheld").reduce((n, c) => n + c.n, 0);
        return `${r.name ?? r.rowId ?? "unnamed"} ${right} of ${r.trials}`;
      })
      .join(", ");
    if (rows.length > 1) lines.push(`By trial type: ${perRow}.`);
  }
  const absent = absentLabels(sim);
  lines.push(absent.length === 0 ? "Every trial type was presented." : `Never presented: ${absent.join("; ")}.`);
  lines.push(`${endedLabel(sim).charAt(0).toUpperCase()}${endedLabel(sim).slice(1)}.`);
  return lines;
}
