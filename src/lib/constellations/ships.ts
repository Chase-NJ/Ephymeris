import type { SceneOrbiter } from "@/components/constellation3d/Orbiters";

/**
 * Cage → spaceship assignment for the 3D constellation.
 *
 * Cagemates share one satellite (`cohorts.md` §2): the crew of animals housed
 * together rides a single craft, and that craft orbits exactly one star at a
 * time. Which star is a two-step rule, shared by Mission Control and the rig
 * view so the same cage never appears in two places:
 *
 *   1. a currently *running* crew member's box, if any member is running;
 *   2. otherwise the box of the most *recently ran* member — the box that
 *      member actually ran on, which is where the operator last saw the cage.
 *
 * An animal with no cage rides solo, which keeps a cohort that never assigned
 * cages looking exactly as it did before cages existed. A crew none of whose
 * members has ever run and none of whose members is mapped anywhere simply has
 * no ship — there is no star to hang it on.
 */
export interface ShipMember {
  id: string;
  name: string;
  /** Home-cage number, or null for a solo craft. */
  cage: number | null;
  /** The box this member is mapped/assigned to right now, or null. */
  box: number | null;
  /** True while this member's box is actually running. */
  running: boolean;
  /** Most recent recorded run — when, and on which box (`RunSummary`). */
  lastRunAt?: string | null;
  lastRunBox?: number | null;
}

/** A ship plus the box whose star it orbits. */
export interface Ship {
  box: number;
  orbiter: SceneOrbiter;
}

/** Latest recorded run per animal, from an `AnalyticsSummary`'s flat run list.
 *  Only runs that know their box can anchor a ship, so runs without one
 *  (adopted orphans — a filename carries no box) are skipped rather than
 *  letting the newest run erase an older, better-informed answer. */
export function lastRunsByAnimal(
  runs: Array<{ animalId: string; boxNumber: number | null; startedAt: string }>,
): Map<string, { at: string; box: number }> {
  const latest = new Map<string, { at: string; box: number }>();
  for (const run of runs) {
    if (run.boxNumber === null) continue;
    const seen = latest.get(run.animalId);
    if (!seen || runTime(run.startedAt) > runTime(seen.at)) {
      latest.set(run.animalId, { at: run.startedAt, box: run.boxNumber });
    }
  }
  return latest;
}

/** Timestamps are ISO in every record this reads, but legacy archives have
 *  surprised this codebase before — an unparseable one sorts oldest. */
function runTime(iso: string): number {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
}

/**
 * Fold members into crews and pick each crew's star. Returns the orbiter lists
 * keyed by box number, ready to hang on the matching `SceneNode`.
 */
export function assignShips(members: ShipMember[]): Map<number, SceneOrbiter[]> {
  const crews = new Map<string, ShipMember[]>();
  for (const member of members) {
    // A solo key per cageless animal: null is "cage unknown", and pooling all
    // the unknowns into one mega-ship would invent a housing fact.
    const key = member.cage === null ? `solo:${member.id}` : `cage:${member.cage}`;
    const crew = crews.get(key) ?? [];
    crew.push(member);
    crews.set(key, crew);
  }

  const byBox = new Map<number, SceneOrbiter[]>();
  for (const [key, crew] of crews) {
    const box = anchorBox(crew);
    if (box === null) continue;
    /*
     * Whoever is running in THIS box is *at* the star, not orbiting it, and
     * leaving their name off the tag is what says so: the ship reads as the
     * cage-mates still waiting their turn. A solo runner therefore leaves the
     * tag empty, which `Orbiters` renders as no tag at all.
     *
     * Matched on the anchor box rather than on `running` alone, because a
     * cage-mate running at some *other* star is not at this one — it still
     * belongs on this tag, since the crew rides a single craft.
     */
    const inOrbit = crew.filter((m) => !(m.running && m.box === box));
    const ships = byBox.get(box) ?? [];
    ships.push({
      id: key,
      name: inOrbit.map((m) => m.name).join(" · "),
      active: crew.some((m) => m.running),
    });
    byBox.set(box, ships);
  }
  return byBox;
}

/** The two-step rule, plus a standing-assignment fallback for a cage that has
 *  never run at all — parked at wherever a member is slated to go. */
function anchorBox(crew: ShipMember[]): number | null {
  const running = crew.find((m) => m.running && m.box !== null);
  if (running) return running.box;

  let lastAt = Number.NEGATIVE_INFINITY;
  let lastBox: number | null = null;
  for (const member of crew) {
    if (member.lastRunBox === null || member.lastRunBox === undefined) continue;
    const t = runTime(member.lastRunAt ?? "");
    if (t > lastAt) {
      lastAt = t;
      lastBox = member.lastRunBox;
    }
  }
  if (lastBox !== null) return lastBox;

  return crew.find((m) => m.box !== null)?.box ?? null;
}
