import { useMemo, useRef } from "react";

import { resolveLayout } from "@/components/chrome/ConstellationStatus";
import { buildSky, type Sky, type SkyOccupant } from "@/lib/sessions/stars";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";

/**
 * The rig's sky, built the one way (`ARCHITECTURE.md#one-sky`).
 *
 * **Every 3D view of the constellation goes through here**, and that is the
 * whole point of the hook rather than three callers assembling the same
 * arguments. The Dashboard, Debug Mode and Mission Control differ only in what
 * is *standing on* the stars — boxes in the rig views, animals in a session —
 * and they must not differ in anything else, because the shared canvas hands one
 * camera between them (`Scene.tsx`). A star that sits at different coordinates
 * in two views turns every navigation between them into a cut, no matter how
 * carefully the camera is eased.
 *
 * > [!CAUTION]
 * > Three inputs decide placement, and **all three have to be identical across
 * > views** — the layout, the seed, and the occupant→box mapping. They drifted
 * > once and each cost something:
 * >
 * > * **The layout.** Mission Control resolved its own, and got `null` when no
 * >   constellation had been chosen — falling back to a per-animal seeded
 * >   scatter while the rig views drew `legacyLayout`. Two different skies.
 * > * **The seed.** It was `constellation?.id ?? ""` in one view and
 * >   `settings.constellation ?? "legacy"` in the other. It seeds per-star depth,
 * >   so on an install with no constellation chosen every star sat at a
 * >   different z.
 * > * **The camera key.** Downstream of the first: a view with no layout keyed
 * >   its camera memory on the cohort instead of the rig's, so the pose never
 * >   crossed over. That one is gone by construction — the camera is a single
 * >   permanent object now and has no key at all (`Scene.tsx`).
 *
 * Resolving the rest in one place is what makes those failures unrepresentable
 * rather than merely fixed.
 */
export function useRigSky(occupants: SkyOccupant[]): Sky {
  const { settings } = useSettings();
  const bound = useBoundBoxes();

  // Reconciled against *bound* boxes, not the caller's occupants: a box's star
  // is a property of the rig, so it must not move because a session's group only
  // runs three of the six.
  const layout = useMemo(
    () => resolveLayout(settings.constellation, settings.constellationSlots, bound),
    [settings.constellation, settings.constellationSlots, bound],
  );
  const seed = settings.constellation ?? LEGACY_SEED;

  /*
   * Keyed on placement alone, deliberately.
   *
   * Mission Control rebuilds its occupant list on every telemetry batch — star
   * temperature rides on it, at the sidecar's 20 Hz — and nothing in a
   * temperature moves a star. Rebuilding the sky at that rate would churn a
   * `BufferGeometry` per link per frame and, far worse, retrigger the camera
   * rig: the view would snap back to the overview several times a second, which
   * makes orbiting and panning both useless.
   */
  const placementKey = occupants.map((o) => `${o.occupantId}:${o.box ?? ""}`).join("|");
  const occupantsRef = useRef(occupants);
  occupantsRef.current = occupants;

  return useMemo(
    () => buildSky(occupantsRef.current, layout, seed),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [placementKey, layout, seed],
  );
}

/** Seed for an install that never chose a constellation and draws
 *  `legacyLayout`. A literal, not `""` — an empty seed reads as "no seed" at a
 *  glance and invites someone to pass a different falsy stand-in. */
const LEGACY_SEED = "legacy";
