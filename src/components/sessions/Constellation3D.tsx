import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import {
  ConstellationScene,
  type SceneLink,
  type SceneNode,
} from "@/components/constellation3d/Scene";
import {
  CORONA_FRAGMENT,
  CORONA_VERTEX,
  STAR_FRAGMENT,
  STAR_VERTEX,
  rampColors,
  temperatureFor,
} from "./starSurface";
import { layoutFor } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { buildSky } from "@/lib/sessions/stars";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The 3D constellation (`starting-a-session.md` §6).
 *
 * **The scene is the rig's own asterism.** Whatever zodiac Box Setup chose, and
 * whichever star each box was slotted onto, is exactly what gets drawn here —
 * the same `box → star` map the sidebar widget and Debug Mode read (§6.1). An
 * animal stands on its box's star; unoccupied stars of the asterism are still
 * drawn, faint, because a rig with two boxes would otherwise show two dots and
 * no constellation at all. An install that never ran Box Setup falls back to
 * the original seeded placement.
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
  const { settings } = useSettings();
  const bound = useBoundBoxes();

  // The chosen asterism, slotted exactly as the sidebar widget slots it. Note
  // this reconciles against *bound* boxes, not the session's boxes: a box's
  // star is a property of the rig, so it must not move because a group only
  // runs three of the six.
  const constellation = zodiacById(settings.constellation);
  const layout = useMemo(
    () =>
      constellation
        ? layoutFor(constellation, settings.constellationSlots, bound)
        : null,
    [constellation, settings.constellationSlots, bound],
  );

  // Keyed on placement alone, deliberately. `animals` takes a fresh identity on
  // every telemetry batch — star temperature rides on it, at the sidecar's
  // 20 Hz — and nothing in a temperature moves a star. Rebuilding the sky at
  // that rate would churn a `BufferGeometry` per link per frame and, far worse,
  // retrigger the camera rig: the view would snap back to the overview several
  // times a second, which makes orbiting and panning both useless.
  const placementKey = animals.map((a) => `${a.animalId}:${a.box ?? ""}`).join("|");
  const animalsRef = useRef(animals);
  animalsRef.current = animals;
  const sky = useMemo(
    () =>
      buildSky(
        cohortId,
        animalsRef.current.map((a) => ({ occupantId: a.animalId, box: a.box ?? null })),
        layout,
        constellation?.id ?? "",
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cohortId, placementKey, layout, constellation],
  );

  const byId = useMemo(() => new Map(animals.map((a) => [a.animalId, a])), [animals]);

  const nodes: SceneNode[] = sky.points.map((point, index) => {
    if (point.occupantId === null) {
      return {
        id: `star-${point.star ?? index}`,
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
      // Every animal mapped to this box rides in orbit around its star, tagged
      // by name — running animals orbit and strobe, assigned-but-idle ones
      // park (`Orbiters.tsx`). Zodiac mode only: there a star *is* the box, so
      // the satellite says "assigned here". In the seeded fallback the star is
      // the animal itself, and a craft orbiting its own namesake would just
      // repeat the nameplate. One animal per box per group means one
      // satellite, but the shape holds if a task ever pairs animals.
      orbiters:
        layout === null || point.box === null
          ? undefined
          : animals
              .filter((a) => a.box === point.box)
              .map((a) => ({ id: a.animalId, name: a.name, active: a.lit })),
      body: lit ? (
        <StellarSurface radius={point.radius} accuracy={animal?.accuracy ?? null} />
      ) : (
        // An unlit star stays a flat matte dot — it has no performance to
        // report, and giving it a surface would imply it were running (§6.2).
        <mesh>
          <sphereGeometry args={[point.radius, 20, 20]} />
          <meshBasicMaterial color={GL.pulsar} transparent opacity={0.34} />
        </mesh>
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

/**
 * A running animal's star: granulated surface plus a rim-only chromosphere,
 * both tinted by the temperature its pooled accuracy earns (`starSurface.ts`).
 *
 * The colour is animated toward its target rather than snapped, so a run of
 * good trials warms the star visibly instead of making it flicker between
 * classes trial by trial.
 */
function StellarSurface({
  radius,
  accuracy,
}: {
  radius: number;
  accuracy: number | null;
}) {
  const reduceMotion = useReduceMotion();

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uCore: { value: new THREE.Color("#ff6a3d") },
      uEdge: { value: new THREE.Color("#8f2d1a") },
      uActivity: { value: 1 },
    }),
    [],
  );
  // Shares the *same* Color instance as the surface, so the rim tracks the
  // temperature for free — lerping one below updates both.
  const coronaUniforms = useMemo(
    () => ({ uCore: { value: uniforms.uCore.value }, uStrength: { value: 0.5 } }),
    [uniforms],
  );

  const target = useMemo(() => rampColors(temperatureFor(accuracy)), [accuracy]);

  useFrame((_state, delta) => {
    if (!reduceMotion) uniforms.uTime.value += delta;
    uniforms.uActivity.value = reduceMotion ? 0 : 1;
    // Ease toward the earned temperature — fast enough to notice within a few
    // trials, slow enough that one lucky trial doesn't recolour the star.
    const k = Math.min(1, delta * 1.2);
    uniforms.uCore.value.lerp(target.core, k);
    uniforms.uEdge.value.lerp(target.edge, k);
  });

  return (
    <group>
      <mesh>
        <sphereGeometry args={[radius, 48, 48]} />
        <shaderMaterial
          vertexShader={STAR_VERTEX}
          fragmentShader={STAR_FRAGMENT}
          uniforms={uniforms}
        />
      </mesh>
      <mesh scale={1.35}>
        <sphereGeometry args={[radius, 32, 32]} />
        <shaderMaterial
          vertexShader={CORONA_VERTEX}
          fragmentShader={CORONA_FRAGMENT}
          uniforms={coronaUniforms}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}
