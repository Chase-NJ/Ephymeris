/**
 * The Boxes step's rules (`ARCHITECTURE.md#mapping-and-the-placement-walk`),
 * pure so they can be tested: the mapping it opens on, whether it may be
 * confirmed, what `sessions.confirmMapping` carries, and the placement walk as
 * one reducer. `SessionMapping` gathers the facts, sends the commands and
 * renders the answers.
 */

import type { Animal } from "@/lib/cohorts/types";

import { defaultConfig, sketchName, type BoxMapping, type TaskProfile } from "./types";

// --- the mapping ----------------------------------------------------------------

/**
 * The mapping the step opens on: the draft the operator left, while it still
 * describes this group's animals, otherwise each animal on its standing box
 * with no sketch chosen. An animal moved or removed in Cohorts meanwhile
 * starts the step over. The draft holds only the operator's own edits, so
 * restoring it cannot carry a default that changed during the visit
 * (`TASKS.md#three-layer-merge`).
 */
export function seedMappings(
  animals: readonly Pick<Animal, "id" | "boxNumber">[],
  draft: BoxMapping[] | undefined,
): BoxMapping[] {
  const sameAnimals =
    draft !== undefined &&
    draft.length === animals.length &&
    draft.every((m) => animals.some((a) => a.id === m.animalId));
  if (sameAnimals) return draft;
  return animals.map((a) => ({
    box: a.boxNumber as number,
    animalId: a.id,
    sketchPath: null,
    overrides: {},
  }));
}

/**
 * The walk order is by **box number**, never by animal: the operator is
 * walking down a bench, and sending them from box 5 to box 2 and back is how
 * an animal ends up in the wrong chamber.
 */
export function placementOrder(mappings: readonly BoxMapping[]): BoxMapping[] {
  return [...mappings].sort((a, b) => a.box - b.box);
}

/** A sketch's profile as fetched: `undefined` not read yet, `null` none (or unreadable). */
export type Profiles = Readonly<Record<string, TaskProfile | null>>;

export interface MappingReadiness {
  /** A box two animals are assigned to, or null. */
  duplicateBox: number | null;
  /** Every box has a sketch whose profile has been read, and no box is shared. */
  allChosen: boolean;
  /** Mapped boxes whose port is in ERROR: a flash would be refused until acknowledged. */
  erroredBoxes: number[];
  /** Mapped boxes with no board bound, in box order. */
  unconfiguredBoxes: number[];
  /** Confirm may be pressed, as far as the mapping goes. */
  ready: boolean;
  /** What stands in the way, in the review's words; null when ready. */
  problem: string | null;
}

/**
 * Whether the mapping may be confirmed. Confirm merges each box's config from
 * its profile, so it waits for every chosen profile: without one the rig layer
 * and the operator's edits would both be dropped from the line. A box in
 * ERROR blocks it too: `ERROR → FLASHING` is refused
 * (`ARCHITECTURE.md#transitions`), so it is acknowledged first. A mapped box
 * with no board is said, not refused: flashing it is a guaranteed failure,
 * worth knowing before the walk reaches it with the rest of the rig flashed.
 */
export function mappingReadiness(
  mappings: readonly BoxMapping[],
  profiles: Profiles,
  portStates: Readonly<Record<number, { state: string } | undefined>>,
  configuredBoxes: ReadonlySet<number>,
): MappingReadiness {
  // Two animals can't share a box — reassigning one here has to displace the
  // other, and the operator is the one who decides which.
  let duplicateBox: number | null = null;
  const seen = new Set<number>();
  for (const m of mappings) {
    if (seen.has(m.box)) {
      duplicateBox = m.box;
      break;
    }
    seen.add(m.box);
  }
  const allChosen =
    mappings.length > 0 &&
    mappings.every((m) => m.sketchPath !== null && profiles[m.sketchPath] !== undefined) &&
    duplicateBox === null;
  const erroredBoxes = mappings.filter((m) => portStates[m.box]?.state === "ERROR").map((m) => m.box);
  const unconfiguredBoxes = [...new Set(mappings.map((m) => m.box))]
    .filter((box) => !configuredBoxes.has(box))
    .sort((a, b) => a - b);
  const problem =
    erroredBoxes.length > 0
      ? `Box ${erroredBoxes.join(", ")} needs acknowledging before it can flash.`
      : duplicateBox !== null
        ? `Two animals share box ${duplicateBox} — move one first.`
        : !allChosen
          ? mappings.every((m) => m.sketchPath !== null)
            ? "Reading the chosen sketches' parameters…"
            : "Pick a sketch for every box, then confirm."
          : null;
  return {
    duplicateBox,
    allChosen,
    erroredBoxes,
    unconfiguredBoxes,
    ready: allChosen && erroredBoxes.length === 0,
    problem,
  };
}

/**
 * The boxes `sessions.confirmMapping` carries: each with its config merged
 * across the three layers (`TASKS.md#three-layer-merge`) from the profiles as
 * they are now — never from a value seeded earlier.
 */
export function confirmPayload(
  mappings: readonly BoxMapping[],
  profiles: Profiles,
  taskDefaults: Readonly<Record<string, Record<string, unknown>>>,
): Array<Omit<BoxMapping, "overrides"> & { config: Record<string, unknown> }> {
  return mappings.map(({ overrides, ...m }) => ({
    ...m,
    config: defaultConfig(
      m.sketchPath ? (profiles[m.sketchPath] ?? null) : null,
      taskDefaults[sketchName(m.sketchPath)] ?? {},
      overrides,
    ),
  }));
}

// --- the walk -------------------------------------------------------------------

/** `review` edits the mapping, `placing` walks the rig, `placed` flashes. */
export type WalkPhase = "review" | "placing" | "placed";

export interface WalkState {
  phase: WalkPhase;
  /** While placing, the stop in `placementOrder` the operator is at; the walk's length once placed. */
  index: number;
  /**
   * The walk has been started, resumed or deliberately left on this visit, so
   * the flash queue is no longer asked where to pick it up.
   */
  resumed: boolean;
}

export const WALK_START: WalkState = { phase: "review", index: 0, resumed: false };

/** `count` is always the walk's length, `placementOrder(...).length`. */
export type WalkAction =
  /** The mapping was confirmed: start the walk, or skip it with every box placed. */
  | { type: "confirmed"; skipWalk: boolean; count: number }
  /** This enclosure is closed (or skipped): on to the next box, or done. */
  | { type: "advance"; count: number }
  /** Every remaining box at once — the operator did the walk without us. */
  | { type: "placeAll"; count: number }
  /** Back one box; from the first, back to editing the mapping. */
  | { type: "retreat" }
  /** The walk again, without re-confirming. */
  | { type: "walkAgain" }
  /** Pick up a walk left mid-way: `at` is `resumeWalkAt(...)`. */
  | { type: "resume"; at: number | null; count: number };

export function walkReducer(state: WalkState, action: WalkAction): WalkState {
  switch (action.type) {
    case "confirmed":
      // The confirm cleared the last mapping's flashes; a walk that leaves
      // from here and comes back resumes this one.
      return action.skipWalk
        ? { phase: "placed", index: action.count, resumed: true }
        : { phase: "placing", index: 0, resumed: true };
    case "advance":
      if (state.phase !== "placing") return state;
      return state.index + 1 >= action.count
        ? { ...state, phase: "placed", index: action.count }
        : { ...state, index: state.index + 1 };
    case "placeAll":
      if (state.phase !== "placing") return state;
      return { ...state, phase: "placed", index: action.count };
    case "retreat":
      if (state.phase !== "placing") return state;
      // From the first box, a deliberate return to the review: not a walk to
      // pick up again.
      return state.index === 0
        ? { phase: "review", index: 0, resumed: true }
        : { ...state, index: state.index - 1 };
    case "walkAgain":
      return { ...state, phase: "placing", index: 0 };
    case "resume":
      // Once per visit, and only while the walk is still to resume.
      if (state.resumed || state.phase !== "review" || action.count === 0 || action.at === null) return state;
      return action.at >= action.count
        ? { phase: "placed", index: action.count, resumed: true }
        : { phase: "placing", index: action.at, resumed: true };
  }
}

/** The mapping the operator is being sent to, or null when not placing. */
export function walkStop(state: WalkState, order: readonly BoxMapping[]): BoxMapping | null {
  return state.phase === "placing" ? (order[state.index] ?? null) : null;
}

/** This animal is in its box, as far as the walk knows. */
export function isPlaced(state: WalkState, order: readonly BoxMapping[], animalId: string): boolean {
  if (state.phase === "placed") return true;
  if (state.phase !== "placing") return false;
  return order.findIndex((m) => m.animalId === animalId) < state.index;
}
