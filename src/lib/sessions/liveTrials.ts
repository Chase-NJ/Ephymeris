/**
 * Live per-trial derivation from the strobe stream (`dashboard.md` §9.4).
 *
 * Pure functions over decoded strobes. Mission Control's live panels are three
 * views of the one trial record this builds, so they can never disagree with
 * each other about what happened.
 *
 * **Keyed off strobe *names*, never raw codes.** `BehaviorBox.h` defines one
 * shared `BF_*` vocabulary and every `task.json` mirrors it by name, so
 * resolving `WATER_POKE_L` → whatever code this sketch assigned keeps the app
 * free of per-sketch knowledge (the rule in CLAUDE.md). A sketch that declares
 * none of these names simply yields no trials, and the panels say so rather
 * than inventing structure.
 *
 * Reads the session store's own strobe log rather than the console ring: the
 * ring is capped at ~2000 lines and a real session emits several thousand
 * strobes, so deriving from it would silently drop the early trials — exactly
 * the part of a learning curve you most want.
 */

import type { StrobeEvent } from "./store";

/** How a trial ended. Ordered as they stack in the outcome chart. */
export type TrialOutcome = "earned" | "hold-fail" | "wrong-well" | "abstained";

export interface TrialRecord {
  /** 1-based completed-trial index. */
  index: number;
  /** The odor strobe code presented, or null if none was seen. */
  odorCode: string | null;
  /** Which well the animal actually went to, if it expressed a choice. */
  went: "left" | "right" | null;
  outcome: TrialOutcome;
  /** Well hold in ms, when the animal poked a well at all. */
  hold: { ms: number; side: "left" | "right"; held: boolean } | null;
}

export interface LiveTrials {
  trials: TrialRecord[];
  /** Odor codes in first-seen order — the chart's series order. */
  odorCodes: string[];
  /** How many strobes have been folded in, so the next pass resumes there. */
  cursor: number;
  /** Trial currently in flight, carried across `advance` calls. */
  pending: Pending;
  /** True once any recognised strobe has been seen. */
  sawAny: boolean;
}

interface Pending {
  odorCode: string | null;
  went: "left" | "right" | null;
  pokedAt: number | null;
  pokedSide: "left" | "right" | null;
  hold: TrialRecord["hold"];
  outcome: TrialOutcome | null;
}

const EMPTY_PENDING: Pending = {
  odorCode: null,
  went: null,
  pokedAt: null,
  pokedSide: null,
  hold: null,
  outcome: null,
};

export const EMPTY_LIVE_TRIALS: LiveTrials = {
  trials: [],
  odorCodes: [],
  cursor: 0,
  pending: EMPTY_PENDING,
  sawAny: false,
};

/**
 * The strobe names this derivation understands, resolved to the codes *this*
 * sketch assigned them. Anything the profile doesn't declare stays undefined
 * and the corresponding transition simply never fires.
 */
export interface StrobeVocab {
  odorOn: Set<string>;
  lightsOn: string | undefined;
  lazy: string | undefined;
  odorUnpokeEarly: string | undefined;
  pokeL: string | undefined;
  pokeR: string | undefined;
  errorL: string | undefined;
  errorR: string | undefined;
  earlyL: string | undefined;
  earlyR: string | undefined;
  fluidL: string | undefined;
  fluidR: string | undefined;
  pokeNone: string | undefined;
  endCorrect: string | undefined;
  endIncorrect: string | undefined;
  invalid: string | undefined;
}

/** Build the vocabulary from a profile's `strobes` map (code → name). */
export function vocabFrom(strobes: Record<string, string>): StrobeVocab {
  const byName = new Map<string, string>();
  const odorOn = new Set<string>();
  for (const [code, name] of Object.entries(strobes)) {
    const upper = name.toUpperCase();
    byName.set(upper, code);
    // `ODOR_<n>_ON` is the per-odor presentation code; the count varies by task.
    if (/^ODOR_\d+_ON$/.test(upper)) odorOn.add(code);
  }
  const at = (name: string) => byName.get(name);
  return {
    odorOn,
    lightsOn: at("LIGHTS_ON"),
    lazy: at("LAZY_RAT"),
    odorUnpokeEarly: at("ODOR_UNPOKE_EARLY"),
    pokeL: at("WATER_POKE_L"),
    pokeR: at("WATER_POKE_R"),
    errorL: at("WATER_POKE_ERROR_L"),
    errorR: at("WATER_POKE_ERROR_R"),
    earlyL: at("WATER_UNPOKE_EARLY_L"),
    earlyR: at("WATER_UNPOKE_EARLY_R"),
    fluidL: at("FLUID_L"),
    fluidR: at("FLUID_R"),
    pokeNone: at("WATER_POKE_NONE"),
    endCorrect: at("END_CORRECT_ITI"),
    endIncorrect: at("END_INCORRECT_ITI"),
    invalid: at("INVALID_TRIAL"),
  };
}

/** Whether a vocabulary carries enough to derive anything worth charting. */
export function vocabIsUsable(vocab: StrobeVocab): boolean {
  return (
    vocab.odorOn.size > 0 &&
    Boolean(vocab.pokeL || vocab.pokeR) &&
    Boolean(vocab.endCorrect || vocab.endIncorrect)
  );
}

/**
 * Fold any strobes past `state.cursor` into the trial record.
 *
 * Returns the same object when nothing new arrived, so React consumers can
 * skip re-rendering. The log is append-only between resets; a log *shorter*
 * than the cursor means the store was reset underneath us, and the caller
 * handles that by starting from `EMPTY_LIVE_TRIALS`.
 */
export function advance(
  state: LiveTrials,
  log: StrobeEvent[],
  vocab: StrobeVocab,
): LiveTrials {
  if (log.length <= state.cursor) return state;

  // Copied once up front: this pass appends to both, and the state object it
  // returns must not share arrays with the one React already rendered.
  const trials = [...state.trials];
  const odorCodes = [...state.odorCodes];
  let pending = state.pending;
  let sawAny = state.sawAny;
  const cursor = log.length;

  for (let i = state.cursor; i < log.length; i += 1) {
    const { code, at } = log[i]!;

    // --- trial boundaries ---------------------------------------------
    if (code === vocab.endCorrect || code === vocab.endIncorrect) {
      sawAny = true;
      trials.push({
        index: trials.length + 1,
        odorCode: pending.odorCode,
        went: pending.went,
        // A trial that reached an ITI with nothing else recorded expressed no
        // choice — that is an abstention, not a silent gap.
        outcome: pending.outcome ?? "abstained",
        hold: pending.hold,
      });
      pending = EMPTY_PENDING;
      continue;
    }

    // --- within a trial -------------------------------------------------
    if (vocab.odorOn.has(code)) {
      sawAny = true;
      pending = { ...pending, odorCode: code };
      if (!odorCodes.includes(code)) odorCodes.push(code);
      continue;
    }

    if (code === vocab.lazy || code === vocab.invalid) {
      sawAny = true;
      // An abort never overrides a real outcome already recorded this trial.
      if (pending.outcome === null) pending = { ...pending, outcome: "abstained" };
      continue;
    }

    if (code === vocab.odorUnpokeEarly) {
      sawAny = true;
      if (pending.outcome === null) pending = { ...pending, outcome: "hold-fail" };
      continue;
    }

    if (code === vocab.pokeL || code === vocab.pokeR) {
      sawAny = true;
      const side = code === vocab.pokeR ? "right" : "left";
      pending = { ...pending, went: side, pokedAt: at, pokedSide: side };
      continue;
    }

    if (code === vocab.errorL || code === vocab.errorR) {
      sawAny = true;
      const side = code === vocab.errorR ? "right" : "left";
      pending = { ...pending, went: side, outcome: "wrong-well" };
      continue;
    }

    if (code === vocab.earlyL || code === vocab.earlyR) {
      sawAny = true;
      const side = code === vocab.earlyR ? "right" : "left";
      pending = {
        ...pending,
        outcome: pending.outcome ?? "hold-fail",
        hold:
          pending.pokedAt !== null
            ? { ms: Math.max(0, at - pending.pokedAt), side, held: false }
            : pending.hold,
      };
      continue;
    }

    if (code === vocab.fluidL || code === vocab.fluidR) {
      sawAny = true;
      const side = code === vocab.fluidR ? "right" : "left";
      pending = {
        ...pending,
        outcome: "earned",
        hold:
          pending.pokedAt !== null
            ? { ms: Math.max(0, at - pending.pokedAt), side, held: true }
            : pending.hold,
      };
      continue;
    }

    if (code === vocab.pokeNone) {
      sawAny = true;
      // Correctly withholding on a no-go trial is a success, not an abstention.
      pending = { ...pending, outcome: "earned" };
      continue;
    }
  }

  return { trials, odorCodes, cursor, pending, sawAny };
}

// --- views over the record -------------------------------------------------

/**
 * Rolling P(went right | odor) per odor, one value per presentation of that
 * odor. Only trials where the animal *expressed* a side count — an abstention
 * is missing data, not evidence of a side preference, and averaging it in as
 * either would be a claim the data doesn't make.
 */
export function rollingRightByOdor(
  trials: TrialRecord[],
  odorCode: string,
  window: number,
): number[] {
  const out: number[] = [];
  const ring: number[] = [];
  for (const trial of trials) {
    if (trial.odorCode !== odorCode || trial.went === null) continue;
    ring.push(trial.went === "right" ? 1 : 0);
    if (ring.length > window) ring.shift();
    out.push(ring.reduce((a, b) => a + b, 0) / ring.length);
  }
  return out;
}

export const OUTCOME_ORDER: TrialOutcome[] = [
  "earned",
  "hold-fail",
  "wrong-well",
  "abstained",
];

/**
 * Cumulative outcome proportions after each completed trial — the stacked
 * bands. Cumulative rather than windowed on purpose: this panel answers "how
 * is the session going overall", and the rolling view is the panel above it.
 */
export function cumulativeOutcomes(
  trials: TrialRecord[],
): Array<Record<TrialOutcome, number>> {
  const counts: Record<TrialOutcome, number> = {
    earned: 0,
    "hold-fail": 0,
    "wrong-well": 0,
    abstained: 0,
  };
  return trials.map((trial, index) => {
    counts[trial.outcome] += 1;
    const total = index + 1;
    return {
      earned: counts.earned / total,
      "hold-fail": counts["hold-fail"] / total,
      "wrong-well": counts["wrong-well"] / total,
      abstained: counts.abstained / total,
    };
  });
}

/**
 * Rolling overall accuracy — the fraction of the last `window` completed
 * trials that earned reward, pooled across every odor.
 *
 * Pooled on purpose, and it is the number the star's temperature reads. A
 * per-condition figure cannot tell learning from a side bias: an animal that
 * always pokes right scores ~1.0 on the go-right odor and ~0.0 on the other,
 * and either alone looks like a story. Pooled, that animal sits at chance,
 * which is the truth (`data.md` §9.7).
 *
 * Abstentions count against it: a trial the animal declined to work is a
 * trial it did not earn, which is exactly what an at-a-glance health readout
 * should reflect.
 */
export function rollingAccuracy(
  trials: TrialRecord[],
  window: number,
): number | null {
  if (trials.length === 0) return null;
  const recent = trials.slice(-window);
  const earned = recent.filter((t) => t.outcome === "earned").length;
  return earned / recent.length;
}

export interface HoldPoint {
  index: number;
  ms: number;
  side: "left" | "right";
  held: boolean;
}

export function holdPoints(trials: TrialRecord[]): HoldPoint[] {
  const out: HoldPoint[] = [];
  for (const trial of trials) {
    if (!trial.hold) continue;
    out.push({
      index: trial.index,
      ms: trial.hold.ms,
      side: trial.hold.side,
      held: trial.hold.held,
    });
  }
  return out;
}

/**
 * The sketch's well-hold requirement, inferred from the data rather than
 * declared: a held trial fires its fluid strobe the instant the hold is
 * satisfied, so the shortest *held* duration is that threshold. Returns null
 * until at least one trial has been held — guessing before then would draw a
 * reference line that later moves.
 */
export function inferHoldThreshold(points: HoldPoint[]): number | null {
  let min: number | null = null;
  for (const point of points) {
    if (!point.held) continue;
    if (min === null || point.ms < min) min = point.ms;
  }
  return min;
}
