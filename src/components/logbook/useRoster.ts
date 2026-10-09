import { useEffect, useMemo, useState } from "react";

import { getCohort } from "@/lib/cohorts/commands";
import { useCohorts } from "@/lib/cohorts/context";
import { useSidecar } from "@/lib/ws/context";

import type { RosterAnimal } from "./tags";

/**
 * A cohort's animals, for naming a note's scope and offering it in a picker.
 *
 * Refetched when the cohort's `updatedAt` moves, so a roster edit in another
 * tab reaches an open Log. An animal since removed from the roster is not
 * here; callers fall back to whatever name the run itself carried.
 */
export function useRoster(cohortId: string | null): RosterAnimal[] {
  const { client, status } = useSidecar();
  const cohorts = useCohorts();
  const stamp = cohorts.find((c) => c.id === cohortId)?.updatedAt ?? null;
  const [roster, setRoster] = useState<{ id: string | null; animals: RosterAnimal[] }>({
    id: null,
    animals: [],
  });

  useEffect(() => {
    if (!cohortId || status !== "connected") return;
    let live = true;
    getCohort(client, cohortId)
      .then((cohort) => {
        if (!live) return;
        setRoster({
          id: cohortId,
          animals: cohort.animals.map((a) => ({ id: a.id, name: a.name, box: a.boxNumber })),
        });
      })
      .catch(() => {
        // An unreadable roster only costs names; notes still render by id.
      });
    return () => {
      live = false;
    };
  }, [client, status, cohortId, stamp]);

  return roster.id === cohortId ? roster.animals : NONE;
}

const NONE: RosterAnimal[] = [];
const NO_FALLBACK: ReadonlyArray<{ id: string; name: string }> = [];

/** id → name, the runs' own names filling in for animals since removed. */
export function useAnimalNames(
  roster: RosterAnimal[],
  // A shared empty default, not `= []`: a fresh array every render would make
  // a fresh Map every render, and the Log's memoized session page with it.
  fallback: ReadonlyArray<{ id: string; name: string }> = NO_FALLBACK,
): Map<string, string> {
  return useMemo(() => {
    const names = new Map(fallback.map((a) => [a.id, a.name]));
    for (const animal of roster) names.set(animal.id, animal.name);
    return names;
  }, [roster, fallback]);
}
