import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { seededRandom } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Cage-ships: one small craft in orbit around a box's star per *home cage*,
 * carrying every animal housed together as one crew (`ships.ts` decides which
 * star a crew orbits — running member first, most recently ran member second).
 * Each ship carries a mini crew tag and a periodic anti-collision strobe — the
 * way you'd know a satellite was up there at all.
 *
 * The craft reads as a made thing at annotation scale: a metal hull with a
 * canopy and fins, *lit by its star* — the belt carries a point light at the
 * star's centre, so a ship shows a day side and a night side as it orbits.
 * That light touches only the ships (everything else in the scene is
 * shader-or-basic material) and is the one place the scene does literal
 * lighting; the ion engine adds a small green exhaust flicker while under way.
 * None of it lands on Pulsar, whose matte flatness §2.2 protects.
 *
 * `active` follows each view's existing motion grammar — stillness is the
 * status. An active ship orbits, burns its engine and strobes; an inactive one
 * parks at its seeded bearing, engine cold, with a steady faint marker light,
 * saying "assigned, not running".
 */
export interface SceneOrbiter {
  /** Stable identity — seeds this ship's orbit, so it never reshuffles.
   *  One per cage (`cage:N`) or per cageless animal (`solo:<id>`). */
  id: string;
  /** The mini tag's text: the crew's names, e.g. `"R-14 · R-15"`. */
  name: string;
  /** Orbit + engine + strobe when true; park with a steady light when false. */
  active: boolean;
}

/** Strobe timing: a quick double-flash, then dark — an aircraft beacon, not a
 *  pulse. Period is per-ship seeded so a full rig never blinks in sync. */
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
  /** Engine-flicker phase offset, so two burns never pulse in sync. */
  burnOffset: number;
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
      {/* The star lights its own fleet. A point light rather than an ambient:
          the day/night line crawling across a hull as it orbits is what makes
          the craft read as a body in space instead of a decal. Standard
          materials exist only on the ships, so nothing else can catch this. */}
      <pointLight
        color={GL.starlight}
        intensity={2.6}
        distance={starRadius * 14}
        decay={1.6}
      />
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
  const exhaust = useRef<THREE.Group>(null);

  // Everything about this orbit is a permanent property of the crew's id —
  // remount the scene, restart the app, same inclination, same bearing.
  const params = useMemo<OrbitParams>(() => {
    const rand = seededRandom(`orbiter:${orbiter.id}`);
    return {
      // Successive ships step outward so two cages anchored on one box ring
      // the star rather than collide.
      reach: 2.6 + index * 0.7 + rand() * 0.35,
      tilt: [0.3 + rand() * 0.55, 0, (rand() - 0.5) * 0.8],
      speed: 0.22 + rand() * 0.26,
      bearing: rand() * Math.PI * 2,
      blinkPeriod: 2.6 + rand() * 2.2,
      blinkOffset: rand() * 5,
      burnOffset: rand() * 7,
    };
  }, [orbiter.id, index]);

  useFrame(({ clock }, delta) => {
    const spin = carousel.current;
    if (spin && orbiter.active && !reduceMotion) {
      spin.rotation.y += delta * params.speed;
    }

    // The engine: a nervous ion flicker while under way, cold when parked.
    const burn = exhaust.current;
    if (burn) {
      let level = 0;
      if (orbiter.active && !reduceMotion) {
        const t = clock.elapsedTime + params.burnOffset;
        level = 0.72 + 0.18 * Math.sin(t * 21) + 0.1 * Math.sin(t * 47);
      } else if (orbiter.active) {
        level = 0.72; // reduced motion: a steady burn, no flicker
      }
      for (const child of burn.children) {
        const mesh = child as THREE.Mesh;
        const material = mesh.material as THREE.MeshBasicMaterial;
        material.opacity = level * Number(mesh.userData["peak"] ?? 1);
      }
      burn.visible = level > 0;
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

  const orbitRadius = starRadius * params.reach;

  return (
    <group rotation={params.tilt}>
      <group ref={carousel} rotation={[0, params.bearing, 0]}>
        <group position={[orbitRadius, 0, 0]}>
          {/* Nose into the direction of travel: the carousel spins +y, which
              moves a craft at +x toward −z. */}
          <ShipHull starRadius={starRadius} active={orbiter.active} exhaust={exhaust} />

          {/* The strobe: a tiny beacon on the spine. */}
          <mesh ref={light} position={[0, starRadius * 0.12, starRadius * 0.02]}>
            <sphereGeometry args={[starRadius * 0.045, 8, 8]} />
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

/**
 * The craft itself, nose toward −z. Everything is sized off the star so the
 * whole ship spans roughly the old octahedron's footprint — it must stay an
 * annotation, never a second star.
 *
 * Hull and fins are standard material so the belt's star-light shades them;
 * the low Halo emissive keeps the night side legible instead of vanishing.
 * Canopy and nozzle stay basic-material accents, and the exhaust is the one
 * additive element — an ion drive's glow, in Ion, animated by the parent.
 */
function ShipHull({
  starRadius: s,
  active,
  exhaust,
}: {
  starRadius: number;
  active: boolean;
  exhaust: React.RefObject<THREE.Group | null>;
}) {
  const hullOpacity = active ? 0.96 : 0.45;

  return (
    <group>
      {/* Fuselage: a capsule laid along z. */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <capsuleGeometry args={[s * 0.055, s * 0.2, 4, 10]} />
        <meshStandardMaterial
          color={GL.starlight}
          metalness={0.45}
          roughness={0.5}
          emissive={GL.halo}
          emissiveIntensity={0.55}
          transparent
          opacity={hullOpacity}
        />
      </mesh>

      {/* Canopy: a small blister forward of midships. */}
      <mesh position={[0, s * 0.045, -s * 0.06]}>
        <sphereGeometry args={[s * 0.032, 10, 10]} />
        <meshBasicMaterial color={GL.pulsar} transparent opacity={hullOpacity * 0.9} />
      </mesh>

      {/* Fins: two swept side planes and a tail, at the stern. */}
      {[
        { position: [s * 0.085, 0, s * 0.08], rotation: [0, -0.35, 0] },
        { position: [-s * 0.085, 0, s * 0.08], rotation: [0, 0.35, 0] },
        { position: [0, s * 0.085, s * 0.08], rotation: [0, 0, Math.PI / 2] },
      ].map((fin, i) => (
        <mesh
          key={i}
          position={fin.position as [number, number, number]}
          rotation={fin.rotation as [number, number, number]}
        >
          <boxGeometry args={[s * 0.11, s * 0.012, s * 0.09]} />
          <meshStandardMaterial
            color={GL.starlight}
            metalness={0.45}
            roughness={0.55}
            emissive={GL.halo}
            emissiveIntensity={0.55}
            transparent
            opacity={hullOpacity}
          />
        </mesh>
      ))}

      {/* Engine nozzle, flaring aft. */}
      <mesh position={[0, 0, s * 0.17]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[s * 0.05, s * 0.032, s * 0.05, 10]} />
        <meshBasicMaterial color={GL.halo} transparent opacity={hullOpacity} />
      </mesh>

      {/* The burn: throat glow plus a tapering plume, additive so it reads as
          light. Opacity is driven per-frame by the parent; `peak` is each
          part's ceiling so throat and plume flicker in ratio. */}
      <group ref={exhaust} visible={false}>
        <mesh position={[0, 0, s * 0.2]} userData={{ peak: 1 }}>
          <sphereGeometry args={[s * 0.028, 8, 8]} />
          <meshBasicMaterial
            color={GL.ion}
            transparent
            opacity={0}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
          />
        </mesh>
        {/* +90° about x points the cone's apex aft, so the plume tapers away
            from the nozzle. */}
        <mesh position={[0, 0, s * 0.29]} rotation={[Math.PI / 2, 0, 0]} userData={{ peak: 0.45 }}>
          <coneGeometry args={[s * 0.022, s * 0.16, 8, 1, true]} />
          <meshBasicMaterial
            color={GL.ion}
            transparent
            opacity={0}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            side={THREE.DoubleSide}
          />
        </mesh>
      </group>
    </group>
  );
}

/** Sharp attack, linear falloff — the shape of a xenon strobe, not a sine. */
function strobe(phase: number, start: number, width: number): number {
  if (phase < start || phase > start + width) return 0;
  return 1 - (phase - start) / width;
}
