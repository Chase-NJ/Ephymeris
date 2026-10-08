import type { SelectionMode, TrialTypeDef } from "./types";

/**
 * How the next trial is chosen, in words, and what each mode leaves unread
 * (`TASKS.md#selection-modes`).
 *
 * A HAND MIRROR OF THE FIRMWARE. `BehaviorBox.h`'s `AntiBiasSelector` and
 * `WeightedAntiBiasSelector`, and `GRGL.ino`'s pool branch — which hands
 * `runTrial` no policy at all — are what these sentences describe. An app-side
 * registry, like `QUICK_TUNE_GROUPS`, because putting mode scope into a profile
 * would move `profile_hash`.
 */

export interface ModeFact {
  label: string;
  on: boolean;
}

export interface ModeInfo {
  value: SelectionMode;
  label: string;
  /** One sentence: how a trial is drawn. */
  hint: string;
  /** What this mode does and does not do, as a row of ✓/✗. */
  facts: ModeFact[];
}

export const SELECTION_MODES: readonly ModeInfo[] = [
  {
    value: "antibias",
    label: "Anti-bias",
    hint:
      "Each trial first draws a side against the animal's recent choices, then a trial type " +
      "on that side at random. It answers a side bias as it forms.",
    facts: [
      { label: "balances sides", on: true },
      { label: "row weights", on: false },
      { label: "correction trials", on: true },
      { label: "lazy escalation", on: true },
      { label: "no-go types", on: false },
    ],
  },
  {
    value: "weighted",
    label: "Weighted",
    hint:
      "The same side draw, then a type on that side by its row weight — show an odor still " +
      "being learned more often. Weights never tilt the session toward one side.",
    facts: [
      { label: "balances sides", on: true },
      { label: "row weights", on: true },
      { label: "correction trials", on: true },
      { label: "lazy escalation", on: true },
      { label: "no-go types", on: false },
    ],
  },
  {
    value: "pool",
    label: "Pool",
    hint:
      "The whole session is dealt at START from the row weights, shuffled in blocks so each " +
      "block keeps the exact proportions. It never reacts to the animal.",
    facts: [
      { label: "balances sides", on: false },
      { label: "row weights", on: true },
      { label: "correction trials", on: false },
      { label: "lazy escalation", on: false },
      { label: "no-go types", on: true },
    ],
  },
];

export function modeInfo(mode: SelectionMode): ModeInfo {
  return SELECTION_MODES.find((m) => m.value === mode) ?? (SELECTION_MODES[0] as ModeInfo);
}

/** Whether a mode reads the row weights at all. */
export function readsWeights(mode: SelectionMode): boolean {
  return mode !== "antibias";
}

/** Whether a mode can present a no-go type. Only the pool: both anti-bias
 *  selectors draw a side first, and a withhold has none. */
export function presentsNoGo(mode: SelectionMode): boolean {
  return mode === "pool";
}

/** Groups the pool ignores outright. */
const POOL_IGNORES = new Set(["Anti-bias selection", "Correction trials"]);

/** The abstention fields that exist only to escalate, which the pool never does. */
const ESCALATION = new Set([
  "lazy_escalation",
  "lazy_escalate_step",
  "lazy_delay_max",
  "lazy_escalation_stage",
]);

/**
 * Whether a whole parameter group does nothing under this mode. Outside the
 * pool, "Trial pool" is its block size alone — the weights are row-owned.
 */
export function groupUnused(mode: SelectionMode, group: string): boolean {
  if (mode === "pool") return POOL_IGNORES.has(group);
  return group === "Trial pool";
}

/**
 * Why a field does nothing under this mode, or null if it is read.
 *
 * The field stays editable — its value survives a switch of mode — and is
 * drawn dimmed with this note beside it.
 */
export function inactiveNote(
  mode: SelectionMode,
  field: { metadataKey: string; group?: string | null },
): string | null {
  const name = modeInfo(mode).label.toLowerCase();
  if (field.metadataKey === "block_size" && mode !== "pool") return `not used in ${name}`;
  if (field.metadataKey === "nogo_well_poll" && !presentsNoGo(mode))
    return "only pool presents no-go";
  if (mode === "pool") {
    if (field.group && POOL_IGNORES.has(field.group)) return "not used in pool";
    if (ESCALATION.has(field.metadataKey)) return "pool never escalates";
  }
  return null;
}

/** One condition's share of the session, as the composition strip draws it. */
export interface Share {
  /** Row index — the condition's colour slot. */
  row: number;
  /** 0–1 of the whole session. 0 for a type this mode never presents. */
  share: number;
  /** Which side half it is drawn in, for the side-balanced modes. */
  side: string | null;
  /** Presented at all under this mode. */
  presented: boolean;
}

/**
 * What fraction of the session each condition gets, for the composition strip.
 *
 * The side-balanced modes split the session evenly between the sides (the
 * long-run expectation of a balanced draw), then within a side uniformly
 * (anti-bias) or by weight (weighted, uniform when the side weighs nothing —
 * the firmware's own fallback). The pool deals by weight across the whole
 * session, uniformly when every weight is zero.
 */
export function compositionOf(trials: readonly TrialTypeDef[], mode: SelectionMode): Share[] {
  if (mode === "pool") {
    const total = trials.reduce((sum, t) => sum + Math.max(t.weight, 0), 0);
    return trials.map((t, row) => ({
      row,
      share: total > 0 ? Math.max(t.weight, 0) / total : 1 / trials.length,
      side: null,
      presented: total > 0 ? t.weight > 0 : true,
    }));
  }

  const sides = new Map<string, number[]>();
  trials.forEach((t, row) => {
    if (!t.isGo || !t.responseChannel) return;
    const list = sides.get(t.responseChannel) ?? [];
    list.push(row);
    sides.set(t.responseChannel, list);
  });
  const perSide = sides.size > 0 ? 1 / sides.size : 0;
  const out: Share[] = trials.map((_, row) => ({ row, share: 0, side: null, presented: false }));
  for (const [side, rows] of sides) {
    const weights = rows.map((row) => Math.max(trials[row]?.weight ?? 0, 0));
    const total = weights.reduce((a, b) => a + b, 0);
    rows.forEach((row, i) => {
      const within =
        mode === "weighted" && total > 0 ? (weights[i] ?? 0) / total : 1 / rows.length;
      out[row] = {
        row,
        share: perSide * within,
        side,
        presented: mode !== "weighted" || total <= 0 || (weights[i] ?? 0) > 0,
      };
    });
  }
  return out;
}
