import { useMemo } from "react";

import { GL } from "@/components/chrome/constellationStyle";
import {
  ConstellationScene,
  type SceneLink,
  type SceneNode,
} from "@/components/constellation3d/Scene";
import { StellarSurface } from "@/components/constellation3d/StellarSurface";
import { useRigSky } from "@/components/constellation3d/useRigSky";
import { assignShips } from "@/lib/constellations/ships";

/**
 * The 3D constellation (`dashboard.md` §9).
 *
 * **The scene is the rig's own asterism** — the very same one the Dashboard and
 * Debug Mode draw, resolved through the very same `useRigSky`. Whatever zodiac
 * Box Setup chose, and whichever star each box was slotted onto, is exactly what
 * gets drawn here (§6.1); an install that never ran Box Setup gets
 * `legacyLayout`, which pins a position per box number. There is no second
 * placement mode and no second sky — see the caution in `stars.ts`.
 *
 * An animal stands on its box's star. Unoccupied stars of the asterism are still
 * drawn, faint, because a rig with two boxes would otherwise show two dots and
 * no constellation at all — and an animal with **no** box in the running group
 * gets no star, because it is not on the rig the sky is a picture of.
 *
 * Camera, controls and the whole animation grammar live in
 * `constellation3d/Scene` and are shared with Debug Mode. What this file owns
 * is what a star *says*: stars whose box is `IN_SESSION` are lit and clickable,
 * everyone else is present but dim and inert (§6.2), and **a lit star's
 * temperature is that animal's pooled rolling accuracy** (`starSurface.ts`) —
 * red at chance through orange and yellow to blue-white as it works, so the
 * overview answers "who is doing well" without opening a panel.
 */

export interface ConstellationAnimal {
  animalId: string;
  name: string;
  /** True only while that animal's box is actually `IN_SESSION`. */
  lit: boolean;
  /** Pooled rolling accuracy, or null before anything has scored. */
  accuracy?: number | null;
  /** The box this animal is mapped to, when it has one. */
  box?: number | null;
  /** Home-cage number — cagemates share one ship (`ships.ts`). */
  cage?: number | null;
  /** Most recent recorded run, for anchoring a parked cage-ship. */
  lastRunAt?: string | null;
  lastRunBox?: number | null;
}

export function Constellation3D({
  cohortId,
  animals,
  focusedId,
  onFocus,
}: {
  cohortId: string;
  animals: ConstellationAnimal[];
  focusedId: string | null;
  onFocus: (animalId: string | null) => void;
}) {
  // The rig's own sky, resolved the one way every view resolves it
  // (`useRigSky`). An animal stands on its box's star; an animal with no box in
  // this group has no star at all, because the sky is the rig.
  const occupants = useMemo(
    () => animals.map((a) => ({ occupantId: a.animalId, box: a.box ?? null })),
    [animals],
  );
  const sky = useRigSky(occupants);

  const byId = useMemo(() => new Map(animals.map((a) => [a.animalId, a])), [animals]);

  // Cagemates share one ship, and the ship orbits the box of its running —
  // else most recently ran — crew member (`ships.ts`). Unconditional now that a
  // star is always the box: a ship says "this cage lives here", which only meant
  // anything once the star stopped being the animal itself. (It used to stand
  // down in the seeded fallback, where a craft would have orbited its own
  // namesake and just repeated the nameplate.)
  const ships = useMemo(
    () =>
      assignShips(
        animals.map((a) => ({
          id: a.animalId,
          name: a.name,
          // This view only ever holds one cohort, so it cannot collide on
          // its own — but the key format is shared, and a crew must get the
          // same id here as it does in the rig views or the same cage would
          // seed a different orbit in each.
          cohortId,
          cage: a.cage ?? null,
          box: a.box ?? null,
          running: a.lit,
          lastRunAt: a.lastRunAt ?? null,
          lastRunBox: a.lastRunBox ?? null,
        })),
      ),
    [animals, cohortId],
  );

  const nodes: SceneNode[] = sky.points.map((point) => {
    if (point.occupantId === null) {
      return {
        id: `star-${point.star}`,
        position: point.position,
        radius: point.radius,
        active: false,
        body: <EmptyStar radius={point.radius} />,
      };
    }
    const animal = byId.get(point.occupantId);
    const lit = animal?.lit ?? false;
    return {
      id: point.occupantId,
      position: point.position,
      radius: point.radius,
      active: lit,
      name: animal?.name ?? "",
      badge: animal?.box ?? null,
      // The cage-ships whose anchor rule chose this box ride in orbit around
      // its star, each tagged with its whole crew — a running crew orbits and
      // strobes, a parked one holds its bearing (`Orbiters.tsx`, `ships.ts`).
      orbiters: point.box === null ? undefined : ships.get(point.box),
      /*
       * **A star is a star whether or not it is recording.**
       *
       * An unlit box used to render as a flat matte dot, on the reasoning that a
       * surface would imply it were running. In practice it read as a
       * placeholder — the whole setup phase, before Start All, showed a sky of
       * dots — and it was the last thing making this view look like a different
       * sky from the Dashboard's: the same box was a dot here and a full star
       * there, so navigating between them changed what the star *was*, which no
       * amount of easing the camera can smooth over.
       *
       * So it takes Debug's treatment for a box that is bound but not on the bus
       * (§4.1): **burned down and frozen**. Stillness and dimness are the status,
       * and neither is a colour — the temperature it earned still reads, which a
       * dot could not show at all. The `dim` scale rides the existing colour
       * lerp, so starting a box fades it up rather than popping it.
       */
      body: (
        <StellarSurface
          radius={point.radius}
          accuracy={animal?.accuracy ?? null}
          churn={lit}
          dim={!lit}
          // **The box, not the animal.** A star is the box in every view now, so
          // its rotation belongs to the box too — seeded on the occupant, box 3
          // turned one way with an animal on it here and another as itself in
          // Debug, and the spin visibly re-seeded on every navigation between
          // them. The same reasoning `buildSky` applies to radius.
          seed={point.box === null ? undefined : `box:${point.box}`}
        />
      ),
    };
  });

  const links: SceneLink[] = sky.links.map(([a, b]) => ({
    a,
    b,
    live: (nodes[a]?.active ?? false) && (nodes[b]?.active ?? false),
  }));

  return (
    <ConstellationScene
      nodes={nodes}
      links={links}
      focusedId={focusedId}
      onFocus={onFocus}
      /*
       * No camera key, because there is nothing to key. The camera is one
       * permanent object (`Scene.tsx`), so a view does not remember a pose or
       * restore one — it inherits whatever the last view left, and eases to the
       * overview if it arrives with nothing focused.
       *
       * That used to be a `persistKey`, conditional on whether a constellation
       * had been chosen: `"rig"` if so, `cohort:<id>` if not, because the
       * fallback drew a per-animal sky the rig's pose pointed nowhere into.
       * Unifying the skies removed the second case and the permanent camera
       * removed the mechanism.
       *
       * Focus is still this view's own state. Selection is separate
       * (`rigSelection`) and is the rig's alone, so a focused box never leaks in
       * as a focused animal.
       */
    />
  );
}

/**
 * An unoccupied star of the chosen asterism — a box that isn't in this group,
 * or a star the rig has no box for at all.
 *
 * Drawn rather than omitted because the asterism is the subject: a two-box rig
 * would otherwise render as two dots and a line, and the constellation the
 * operator picked in Box Setup would be invisible in the one view that is
 * mostly constellation. Kept markedly fainter and smaller than any animal's
 * star so it never competes with the data — it is scenery, and inert.
 */
function EmptyStar({ radius }: { radius: number }) {
  return (
    <mesh>
      <sphereGeometry args={[radius, 12, 12]} />
      <meshBasicMaterial color={GL.halo} transparent opacity={0.55} />
    </mesh>
  );
}

