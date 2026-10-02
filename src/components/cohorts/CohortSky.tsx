import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { MAX_FRAME_SECONDS } from "@/components/constellation3d/CameraRig";
import { PlanetarySurface } from "@/components/constellation3d/PlanetarySurface";
import { useProgramsWarm } from "@/components/constellation3d/ProgramWarmth";
import {
  ConstellationScene,
  type SceneNode,
} from "@/components/constellation3d/Scene";
import type { SceneOrbiter } from "@/components/constellation3d/Orbiters";
import {
  livelinessFor,
  planetPalette,
  radiusFor,
  resolveAppearance,
  type ResolvedAppearance,
} from "@/lib/cohorts/appearance";
import { planetSlots } from "@/lib/constellations/cohortSky";
import type { CohortSummary } from "@/lib/cohorts/types";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The cohort browser — one world per cohort, in a sky you pan across.
 *
 * It replaced two near-identical card grids (`/cohorts` and Analytics' landing)
 * with the stage the app already owned and only the rig views used. Everything
 * that makes a planet behave like the rig's stars — the hover swell and pointer
 * cursor, the sweeping reticle, the nameplate, the arrival rings, the eased
 * flight on click, click-away to deselect — is `ConstellationScene`'s and
 * arrives by passing nodes. Nothing here re-implements any of it, and nothing
 * here touches the camera: views declare a subject, the rig flies it
 * (`sceneIntent.ts`).
 *
 * **This view IS the route's constellation.** `/cohorts` and Analytics' landing
 * mount it *instead of* `SkyBackdrop`, the way the Dashboard mounts
 * `DebugConstellation` — which keeps the invariant that every route mounts some
 * constellation, and so keeps the shared canvas from ever being torn down
 * (`SharedCanvas.tsx`).
 *
 * **Search dims; it does not filter.** A world stays where you learned it was,
 * which is the whole return on spending a spatial layout: `dimmed` drops a
 * planet's interactivity and pushes it back toward the sky rather than removing
 * it and letting its neighbours close the gap on every keystroke.
 */
export function CohortSky({
  cohorts,
  focusedId,
  onFocus,
  dimmed,
  onCreate,
  frameShift = 0,
}: {
  /** In the order they should take slots — the sort control decides this. */
  cohorts: CohortSummary[];
  focusedId: string | null;
  onFocus: (id: string | null) => void;
  /** Ids search has ruled out. Still drawn, still in place, not clickable. */
  dimmed?: ReadonlySet<string>;
  /** Given, the innermost slot becomes the unformed world that makes one. */
  onCreate?: () => void;
  /** Left-shift for a docked panel, in px — the browser's own geometry. */
  frameShift?: number;
}) {
  // The proto disc takes the innermost slot, so the worlds all shift out by
  // one. Counted here rather than inside `planetSlots` because the layout has
  // no opinion about what fills a slot.
  const offset = onCreate ? 1 : 0;

  /*
   * Two things the sky waits for, and neither of them is allowed to be a
   * frozen window.
   *
   * `warm` — the planet shader is linked (`ProgramWarmth.tsx`). Normally true
   * long before anyone gets here; when the app opens straight onto this route
   * it is not, and drawing a real world then would block on the link for
   * seconds. Until it is, a world is a flat disc in its own colour.
   *
   * `fleetsReady` — the ships mount one frame after the planets. A library's
   * fleet is around a hundred craft; building them in the same commit as the
   * worlds made the sky's first frame wait on its least important content.
   */
  const warm = useProgramsWarm();
  const [fleetsReady, setFleetsReady] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setFleetsReady(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  const slots = useMemo(
    () => planetSlots(cohorts.length + offset),
    [cohorts.length, offset],
  );

  const nodes = useMemo<SceneNode[]>(() => {
    const worlds: SceneNode[] = cohorts.map((cohort, i) => {
      const index = i + offset;
      {
        const appearance = resolveAppearance(cohort.id, cohort.appearance);
        const radius = radiusFor(cohort.animalCount);
        const faded = dimmed?.has(cohort.id) ?? false;
        return {
          id: cohort.id,
          position: slots[index]?.position ?? [0, 0, 0],
          radius,
          // A search miss is inert as well as dim: a planet that still swelled
          // and took a click while reading as ruled out would be saying two
          // things at once.
          active: !faded,
          name: cohort.name,
          badge: null,
          body: (
            <PlanetBody
              appearance={appearance}
              radius={radius}
              cohort={cohort}
              faded={faded}
              warm={warm}
            />
          ),
          // One craft per home cage. `Orbiters` already keys ships this way —
          // cohort-scoped, because cage numbers restart in every cohort — so a
          // cohort's fleet needs no new machinery, only the count.
          orbiters: faded || !fleetsReady ? undefined : fleetFor(cohort),
        };
      }
    });

    if (!onCreate) return worlds;
    return [
      {
        // A reserved id, not a cohort's: `onFocus` reads it and navigates
        // rather than docking the panel, because there is nothing to inspect
        // yet. Underscored so it can never collide with a uuid.
        id: NEW_COHORT_ID,
        position: slots[0]?.position ?? [0, 0, 0],
        radius: 0.5,
        active: true,
        name: "New cohort",
        badge: null,
        body: <ProtoDisc radius={0.5} />,
      },
      ...worlds,
    ];
  }, [cohorts, slots, dimmed, offset, onCreate, warm, fleetsReady]);

  return (
    <ConstellationScene
      nodes={nodes}
      // Cohorts are not adjacent to one another in any sense worth drawing. The
      // rig's links mean "these two boxes are neighbours on the bench"; a line
      // between two studies would mean nothing and would read as if it did.
      links={EMPTY_LINKS}
      focusedId={focusedId}
      onFocus={(id) => (id === NEW_COHORT_ID ? onCreate?.() : onFocus(id))}
      docksPanel
      frameShift={frameShift}
    />
  );
}

const EMPTY_LINKS: never[] = [];

/** The reserved node id the create affordance occupies. */
export const NEW_COHORT_ID = "__new_cohort__";

/**
 * The unformed world — "+ New Cohort", as a protoplanetary disc.
 *
 * The metaphor is *a nebula that hasn't collapsed into a star system yet*.
 * In a sky of finished worlds it can finally be drawn rather than described.
 *
 * Deliberately NOT a planet: no surface, no atmosphere, no terminator. A dust
 * ring around one slow point, in the Halo the app uses for everything inert,
 * with the accent only on the seed at the centre. If it were a dim planet it
 * would read as a cohort someone had already made and left dark.
 */
function ProtoDisc({ radius }: { radius: number }) {
  const reduceMotion = useReduceMotion();
  const disc = useRef<THREE.Group>(null);
  const core = useRef<THREE.Mesh>(null);
  const clock = useRef(0);

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (reduceMotion) return;
    // A local clock, never `clock.elapsedTime`: r3f zeroes that on every
    // frameloop transition, which would jump the pulse (`Orbiters.tsx`).
    clock.current += delta;
    if (disc.current) disc.current.rotation.z += delta * 0.12;
    if (core.current) {
      const material = core.current.material as THREE.MeshBasicMaterial;
      material.opacity = 0.45 + 0.35 * Math.sin(clock.current * 1.1);
    }
  });

  return (
    <group>
      {/* Open, not edge-on. At the tilt a planet's own ring wears (~90°) these
          were a few pixels of nothing — a ring reads as a ring because it is a
          ring the camera can see INTO, and this one has no sphere in front of
          it to imply the plane. */}
      <group ref={disc} rotation={[Math.PI / 3.2, 0, 0]}>
        {/* Bands, not hairlines. At the overview a 0.014-wide ring is under a
            pixel and the whole affordance simply vanished — which for the one
            control that makes a new cohort is the worst possible failure. */}
        {[1.4, 2.0, 2.7].map((scale, i) => (
          <mesh key={scale}>
            <ringGeometry args={[radius * scale, radius * (scale + 0.34), 64]} />
            <meshBasicMaterial
              color={GL.halo}
              transparent
              opacity={0.42 - i * 0.1}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ))}
      </group>
      <mesh ref={core}>
        <sphereGeometry args={[radius * 0.42, 16, 16]} />
        {/* `GL.pulsar`, not `NODE_PRIMARY`: the latter is the CSS var the 2D
            chrome uses, and a material cannot read one. */}
        <meshBasicMaterial color={GL.pulsar} transparent opacity={0.5} />
      </mesh>
    </group>
  );
}

/**
 * The world, plus the dimming a search miss gets.
 *
 * Dimming is a black shell rather than a change to the planet's own colours:
 * the surface material is opaque and lerps its palette every frame, so fading
 * it there would fight the appearance editor's live preview. A veil is one
 * extra draw and composes with anything underneath it.
 */
function PlanetBody({
  appearance,
  radius,
  cohort,
  faded,
  warm,
}: {
  appearance: ResolvedAppearance;
  radius: number;
  cohort: CohortSummary;
  faded: boolean;
  /** The planet shader is linked; before that, draw the stand-in. */
  warm: boolean;
}) {
  return (
    <group>
      {warm ? (
        <PlanetarySurface
          radius={radius}
          appearance={appearance}
          liveliness={livelinessFor(cohort.updatedAt)}
          seed={cohort.id}
        />
      ) : (
        <PlanetStandIn radius={radius} appearance={appearance} />
      )}
      {faded && (
        <mesh scale={1.06}>
          <sphereGeometry args={[radius, 24, 24]} />
          <meshBasicMaterial
            color={GL.void}
            transparent
            opacity={0.72}
            depthWrite={false}
            side={THREE.FrontSide}
          />
        </mesh>
      )}
    </group>
  );
}

/**
 * A world before its shader is ready: the right size, in the right place, in
 * its own dominant colour, and nothing else.
 *
 * Deliberately featureless. It exists for the seconds between the app opening
 * onto this route and `ProgramWarmth` finishing, and what matters in those
 * seconds is that the sky pans, the nameplates read and a click lands — every
 * one of which the scene gives a node regardless of its body. A basic material
 * links in milliseconds, which is the whole reason it can stand in.
 */
function PlanetStandIn({
  radius,
  appearance,
}: {
  radius: number;
  appearance: ResolvedAppearance;
}) {
  const colour = useMemo(() => planetPalette(appearance).core, [appearance]);
  return (
    <mesh>
      <sphereGeometry args={[radius, 24, 24]} />
      <meshBasicMaterial color={colour} transparent opacity={0.55} />
    </mesh>
  );
}

/**
 * A cohort's fleet: one ship per home cage.
 *
 * `active: false` on every craft, and that is not an oversight — "active" means
 * *this crew is running right now*, which is a fact about the rig and about a
 * session in flight. This is a library view; nothing here is running. A coasting
 * ship still orbits, still blinks its beacon and still carries its navigation
 * lamps (`Orbiters.tsx`), which is what a satellite between manoeuvres looks
 * like, so a quiet fleet does not read as a dead one.
 *
 * The tags are empty because a summary carries a cage COUNT, not the roster:
 * naming crews here would cost a full `cohorts.get` per planet on every route
 * mount, and `Orbiters` skips the DOM overlay entirely for an empty name.
 */
function fleetFor(cohort: CohortSummary): SceneOrbiter[] | undefined {
  if (cohort.cageCount <= 0) return undefined;
  return Array.from({ length: Math.min(cohort.cageCount, MAX_SHIPS) }, (_, i) => ({
    // The id `Orbiters` expects, and the one the rig views already use for the
    // same cage — so a cage keeps its orbit between the two.
    id: `cage:${cohort.id}:${i + 1}`,
    name: "",
    active: false,
  }));
}

/** Past this the belt is a smear rather than a count, and each craft is a real
 *  draw with its own lamps. A cohort with more cages than this is telling you
 *  "many", which is the honest reading either way. */
const MAX_SHIPS = 8;
