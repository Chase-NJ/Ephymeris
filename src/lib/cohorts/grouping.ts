/**
 * Auto-Balance grouping — `cohorts.md` §7.
 *
 * A client-side mirror of `sidecar/ephymeris_sidecar/cohorts/grouping.py`, so
 * the suggest-a-grouping tool can run against an in-memory, not-yet-saved
 * roster (`CohortEditor` builds a whole cohort locally before its first
 * `cohorts.create`/`cohorts.update` round trip). The algorithm is a balanced
 * round-robin, deliberately not an optimization search — simple, deterministic,
 * and easy to explain when a user asks why an animal landed where it did.
 *
 * Keep this in sync with `grouping.py` by hand — same instinct as the
 * `protocol.ts`/`protocol.py` wire mirrors, just without a contract test,
 * since this isn't wire surface. `sidecar/tests/test_grouping.py` is the
 * behavioral spec both sides need to satisfy.
 */

import { MAX_GROUP_SIZE, type Animal, type GroupProposal } from "./types";

/** §7.3 step 1 — buckets are walked in this order so the result is stable. */
const SEX_BUCKETS: Array<"M" | "F" | null> = ["M", "F", null];

/** §7.2 — the fewest groups that can hold this roster. */
export function minimumGroupCount(animalCount: number): number {
  return Math.max(1, Math.ceil(animalCount / MAX_GROUP_SIZE));
}

/** §7.1 — the user gives one of the two; the other is derived. */
export function resolveGroupCount(
  animalCount: number,
  groupCount: number | null | undefined,
  maxGroupSize: number | null | undefined,
): number {
  if (groupCount != null && groupCount > 0) return groupCount;
  if (maxGroupSize != null && maxGroupSize > 0) {
    return Math.max(1, Math.ceil(animalCount / maxGroupSize));
  }
  // Neither supplied: fall back to the smallest workable split.
  return minimumGroupCount(animalCount);
}

/** Only M/F carry balancing information; `unknown` and null are the same. */
function bucketOf(animal: Animal): "M" | "F" | null {
  return animal.sex === "M" || animal.sex === "F" ? animal.sex : null;
}

/**
 * Propose a complete grouping (§7.3).
 *
 * Always a **full re-proposal** — it considers the entire roster and ignores
 * whatever grouping already exists (§7.4). Nothing is written; the caller
 * previews this and applies it into local state.
 */
export function suggestGroupsLocal(
  animals: Animal[],
  options: { groupCount?: number | null; maxGroupSize?: number | null; balanceBySex?: boolean },
): GroupProposal {
  const roster = animals;
  const target = resolveGroupCount(roster.length, options.groupCount, options.maxGroupSize);

  // §7.2 — reject rather than silently producing an unassignable group.
  const minimum = minimumGroupCount(roster.length);
  if (roster.length > 0 && target < minimum) {
    return {
      groups: [],
      rejected: {
        reason:
          `${roster.length} animals can't fit in ${target} ` +
          `group${target !== 1 ? "s" : ""} — no group may exceed ` +
          `${MAX_GROUP_SIZE}, since box numbers only span 1–${MAX_GROUP_SIZE}.`,
        minimumGroups: minimum,
      },
    };
  }

  const buckets = new Map<"M" | "F" | null, Animal[]>(SEX_BUCKETS.map((k) => [k, []]));
  for (const animal of roster) {
    // With balancing off everything shares one bucket, which reduces the walk
    // below to a plain round-robin over the roster.
    const key = options.balanceBySex ? bucketOf(animal) : null;
    buckets.get(key)!.push(animal);
  }

  const assigned: Animal[][] = Array.from({ length: target }, () => []);

  // §7.3 step 2: walk each bucket in turn, cycling group index. Continuing the
  // cursor *across* buckets rather than restarting at 0 is what keeps overall
  // group sizes within one of each other — restarting would pile every
  // bucket's first few animals onto the low-numbered groups.
  let cursor = 0;
  for (const key of SEX_BUCKETS) {
    for (const animal of buckets.get(key)!) {
      assigned[cursor % target]!.push(animal);
      cursor += 1;
    }
  }

  return {
    groups: assigned.map((members, index) => ({
      name: `Group ${index + 1}`,
      order: index,
      // §7.3 step 4 — boxes number sequentially in landing order, making the
      // tedious part a byproduct of grouping.
      animals: members.map((a, slot) => ({ animalId: a.id, boxNumber: slot + 1 })),
    })),
    rejected: null,
  };
}
