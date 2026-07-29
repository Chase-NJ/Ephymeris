import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { seededRandom } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Animal satellites: one small craft in orbit around a box's star for each
 * animal assigned to that box, each carrying a mini name tag and a periodic
 * anti-collision strobe — the way you'd know a satellite was up there at all.
 *
 * The callers decide who orbits what. Mission Control puts the mapped animal
 * of the current group around its box's star; Debug Mode reads the running
 * session's mapping, so the rig view answers "who is in box 3 right now"
 * without leaving the hardware picture. Either way the satellite is an
 * *annotation* on the star, never a second star: the body is a fraction of the
 * star's radius and the tag is deliberately smaller and fainter than the
 * star's own nameplate.
 *
 * `active` follows each view's existing motion grammar — stillness is the
 * status. An active satellite orbits and strobes; an inactive one parks at its
 * seeded bearing with a steady faint light, saying "assigned, not running".
 */
export interface SceneOrbiter {
  /** Stable identity — seeds this satellite's orbit, so it never reshuffles. */
  id: string;
  /** The mini tag's text: the animal's name. */
  name: string;
  /** Orbit + strobe when true; park with a steady light when false. */
  active: boolean;
}

/** Strobe timing: a quick double-flash, then dark — an aircraft beacon, not a
 *  pulse. Period is per-satellite seeded so a full rig never blinks in sync. */
const FLASH_SECONDS = 0.11;
const SECOND_FLASH_AT = 0.32;

interface OrbitParams {
  /** Orbit radius in multiples of the star's radius. */
  reach: number;
  tilt: [number, number, number];
  speed: number;
  bearing: number;
  blinkPeriod: number;
  blinkOffset: number;
}

export function OrbiterBelt({
  orbiters,
  starRadius,
}: {
  orbiters: SceneOrbiter[];
  starRadius: number;
}) {
  return (
    <group>
      {orbiters.map((orbiter, index) => (
        <Orbiter
          key={orbiter.id}
          orbiter={orbiter}
          starRadius={starRadius}
          index={index}
        />
      ))}
    </group>
  );
}

function Orbiter({
  orbiter,
  starRadius,
  index,
}: {
  orbiter: SceneOrbiter;
  starRadius: number;
  index: number;
}) {
  const reduceMotion = useReduceMotion();
  const carousel = useRef<THREE.Group>(null);
  const light = useRef<THREE.Mesh>(null);

  // Everything about this orbit is a permanent property of the animal's id —
  // remount the scene, restart the app, same inclination, same bearing.
  const params = useMemo<OrbitParams>(() => {
    const rand = seededRandom(`orbiter:${orbiter.id}`);
    return {
      // Successive satellites step outward so two animals on one box (a
      // multi-animal task someday) ring the star rather than collide.
      reach: 2.6 + index * 0.7 + rand() * 0.35,
      tilt: [0.3 + rand() * 0.55, 0, (rand() - 0.5) * 0.8],
      speed: 0.22 + rand() * 0.26,
      bearing: rand() * Math.PI * 2,
      blinkPeriod: 2.6 + rand() * 2.2,
      blinkOffset: rand() * 5,
    };
  }, [orbiter.id, index]);

  useFrame(({ clock }, delta) => {
    const spin = carousel.current;
    if (spin && orbiter.active && !reduceMotion) {
      spin.rotation.y += delta * params.speed;
    }

    const beacon = light.current;
    if (!beacon) return;
    const material = beacon.material as THREE.MeshBasicMaterial;
    if (!orbiter.active || reduceMotion) {
      // Parked: a steady faint marker light, no theatre.
      material.opacity = orbiter.active ? 0.5 : 0.28;
      beacon.scale.setScalar(1);
      return;
    }
    const phase = (clock.elapsedTime + params.blinkOffset) % params.blinkPeriod;
    const flash =
      strobe(phase, 0, FLASH_SECONDS) + strobe(phase, SECOND_FLASH_AT, FLASH_SECONDS);
    material.opacity = 0.14 + flash * 0.86;
    beacon.scale.setScalar(1 + flash * 1.4);
  });

  const bodyOpacity = orbiter.active ? 0.9 : 0.4;
  const orbitRadius = starRadius * params.reach;

  return (
    <group rotation={params.tilt}>
      <group ref={carousel} rotation={[0, params.bearing, 0]}>
        <group position={[orbitRadius, 0, 0]}>
          {/* The craft: a small matte octahedron — angular, so it reads as a
              made thing next to the round star. */}
          <mesh>
            <octahedronGeometry args={[starRadius * 0.14, 0]} />
            <meshBasicMaterial
              color={GL.starlight}
              transparent
              opacity={bodyOpacity}
            />
          </mesh>

          {/* The strobe: a tiny beacon just off the hull. */}
          <mesh ref={light} position={[0, starRadius * 0.2, 0]}>
            <sphereGeometry args={[starRadius * 0.055, 8, 8]} />
            <meshBasicMaterial
              color={GL.starlight}
              transparent
              opacity={0.28}
              depthWrite={false}
            />
          </mesh>

          {/* The mini tag. DOM, like the nameplates, so it stays crisp — but a
              step smaller and fainter: this labels an annotation, and it must
              never outrank the star's own plate. */}
          <Html
            center
            position={[0, starRadius * 0.55, 0]}
            style={{ pointerEvents: "none", userSelect: "none" }}
            zIndexRange={[10, 0]}
          >
            <span
              className="whitespace-nowrap font-mono text-[8px] leading-none"
              style={{
                color: "var(--color-static)",
                opacity: orbiter.active ? 0.9 : 0.55,
                textShadow: "0 0 4px var(--color-void), 0 0 2px var(--color-void)",
              }}
            >
              {orbiter.name}
            </span>
          </Html>
        </group>
      </group>
    </group>
  );
}

/** Sharp attack, linear falloff — the shape of a xenon strobe, not a sine. */
function strobe(phase: number, start: number, width: number): number {
  if (phase < start || phase > start + width) return 0;
  return 1 - (phase - start) / width;
}
