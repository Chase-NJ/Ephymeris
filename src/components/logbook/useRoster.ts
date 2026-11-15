import { useEffect, useMemo, useState } from "react";

import { getCohort } from "@/lib/cohorts/commands";
import { useCohorts } from "@/lib/cohorts/context";
import { useSidecar } from "@/lib/ws/context";

import type { RosterAnimal } from "./tags";

/** An animal with history in the cohort but off its roster, by name only. */
export interface FormerName {
  id: string;
  name: string;
}

interface Members {
  animals: RosterAnimal[];
  former: ReadonlyArray<FormerName>;
}

/**
 * A cohort's animals, for naming a note's scope and offering it in a picker —
 * plus its former members (`DATA.md#former-members`), which name history but
 * are never offered as a scope by this hook.
 *
 * Refetched when the cohort's `updatedAt` moves, so a roster edit in another
 * tab reaches an open Log.
 */
export function useRoster(cohortId: string | null): Members {
  const { client, status } = useSidecar();
  const cohorts = useCohorts();
  const stamp = cohorts.find((c) => c.id === cohortId)?.updatedAt ?? null;
  const [roster, setRoster] = useState<{ id: string | null } & Members>({
    id: null,
    ...NONE,
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
          former: cohort.formerAnimals.flatMap((a) =>
            a.name === null ? [] : [{ id: a.id, name: a.name }],
          ),
        });
      })
      .catch(() => {
        // An unreadable roster only costs names; notes still render by id.
      });
    return () => {
      live = false;
    };
  }, [client, status, cohortId, stamp]);

  return roster.id === cohortId ? roster : NONE;
}

const NONE: Members = { animals: [], former: [] };

/** id → name: the roster, with former members filling in for animals since removed. */
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

const NO_FALLBACK: ReadonlyArray<{ id: string; name: string }> = [];
