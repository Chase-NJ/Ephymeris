import { Html } from "@react-three/drei";
import { MAX_FRAME_SECONDS } from "./CameraRig";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { GL, GL_NAV } from "@/components/chrome/constellationStyle";
import { seededRandom } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

import { SHIP_GEOMETRY, createHullMaterial } from "./shipSurface";

/**
 * Cage-ships: one small craft in orbit around a box's star per *home cage*,
 * carrying every animal housed together as one crew (`ships.ts` decides which
 * star a crew orbits — running member first, most recently ran member second).
 * Each ship carries a mini crew tag and a periodic anti-collision strobe — the
 * way you'd know a satellite was up there at all.
 *
 * The craft reads as a made thing at annotation scale: a metal hull with a
 * canopy and fins, *lit by its star* — a ship shows a day side and a night side
 * as it orbits. That shading is `shipSurface.ts`'s, computed from the direction
 * of the belt's centre; **the scene contains no lights**, because a light's
 * mere presence is part of every program's cache key and one per belt made the
 * whole scene relink whenever a fleet appeared or left (see that module). The
 * ion engine adds a small green exhaust flicker while under way. None of it
 * lands on Pulsar, whose matte flatness §2.2 protects.
 *
 * **Every ship orbits, always.** The craft used to park when its crew wasn't
 * running, on the app's "stillness is the status" grammar, but the fleet is not
 * where hardware state belongs: a rig whose boxes are mostly disconnected then
 * read as a frozen picture rather than a sky. An undetected box says so by
 * burning its *star* down instead (`StellarSurface`'s `dim`).
 *
 * **Every ship keeps its lights, too**: a white anti-collision beacon
 * double-flashing on the spine, and port-red / starboard-green navigation
 * lamps swelling slowly on the hull sides (`GL_NAV`). A dark satellite reads as
 * debris, and a crew that is merely waiting its turn is not debris.
 *
 * So `active` — the crew is running — is a matter of *degree* rather than
 * on/off. A running ship travels at full speed, burns its ion engine, and
 * carries its lights at full brightness; a coasting one still travels, still
 * blinks, still swells, just slower and dimmer, with the engine cold. That is
 * what a satellite between manoeuvres actually looks like.
 */
export interface SceneOrbiter {
  /** Stable identity — seeds this ship's orbit, so it never reshuffles. One per
   *  cage (`cage:<cohortId>:<n>`) or per cageless animal (`solo:<id>`). The
   *  cohort is part of the key because cage numbers restart per cohort
   *  (`ships.ts`); without it two cohorts' cage 3 shared a hull. */
  id: string;
  /** The mini tag's text: the crew members still in orbit, e.g. `"R-14 · R-15"`.
   *  Whoever is running in the box below is omitted — they are at the star, not
   *  riding — so this is **empty** for a solo animal that is running, and no tag
   *  is drawn at all (`ships.ts`'s `assignShips`). */
  name: string;
  /** The crew is running. Engine + strobe when true; cold engine and a steady
   *  marker light when false. **Not** the orbit — that never stops. */
  active: boolean;
}

/** Strobe timing: a quick double-flash, then dark — an aircraft beacon, not a
 *  pulse. Period is per-ship seeded so a full rig never blinks in sync. */
const FLASH_SECONDS = 0.11;
const SECOND_FLASH_AT = 0.32;
/** The second flash of the pair, a touch weaker than the first — real beacons
 *  are not two identical pulses, and the unevenness is most of what sells it. */
const SECOND_FLASH_PEAK = 0.82;
/**
 * How fast a coasting ship orbits, against a running one. Slow enough to read
 * instantly as "this crew is waiting", fast enough to still be visibly under
 * way — the point of the change is that a parked cage is *alive*, not frozen.
 */
const COASTING_SPEED = 0.22;
/** A coasting ship's lights against a running one's. Dimmer, never dark. */
const COASTING_LIGHTS = 0.7;
/** Nav-light breathe, in radians/second — a slow swell, not a blink. */
const BREATHE_RATE = 1.05;

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
  /** Nav-light breathe phase, so no two hulls swell together either. */
  navOffset: number;
}

export function OrbiterBelt({
  orbiters,
  starRadius,
}: {
  orbiters: SceneOrbiter[];
  starRadius: number;
}) {
  const belt = useRef<THREE.Group>(null);

  /*
   * The star lights its own fleet — as a direction, not as a light. The
   * day/night line crawling across a hull as it orbits is what makes the craft
   * read as a body in space instead of a decal, and `shipSurface.ts` gets it
   * from where the belt's centre is. One `uStar` object is shared by every
   * material below, so writing the position once reaches the whole fleet.
   *
   * Materials are per BELT, in the two opacities a ship can wear, rather than
   * per ship: a fleet of eight was thirty-two hull materials for two looks.
   */
  const paint = useMemo(() => {
    const star = { value: new THREE.Vector3() };
    const accent = (color: string, opacity: number) =>
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity });
    return {
      star,
      running: {
        hull: createHullMaterial(star, HULL_OPACITY.running),
        canopy: accent(GL.pulsar, HULL_OPACITY.running * 0.9),
        nozzle: accent(GL.halo, HULL_OPACITY.running),
      },
      coasting: {
        hull: createHullMaterial(star, HULL_OPACITY.coasting),
        canopy: accent(GL.pulsar, HULL_OPACITY.coasting * 0.9),
        nozzle: accent(GL.halo, HULL_OPACITY.coasting),
      },
    };
  }, []);
  useEffect(
    () => () => {
      for (const look of [paint.running, paint.coasting]) {
        look.hull.dispose();
        look.canopy.dispose();
        look.nozzle.dispose();
      }
    },
    [paint],
  );

  // Every frame rather than once: a node's position is a prop, and the cost is
  // one matrix read per belt.
  useFrame(() => {
    belt.current?.getWorldPosition(paint.star.value);
  });

  return (
    <group ref={belt}>
      {orbiters.map((orbiter, index) => (
        <Orbiter
          key={orbiter.id}
          orbiter={orbiter}
          starRadius={starRadius}
          index={index}
          paint={orbiter.active ? paint.running : paint.coasting}
        />
      ))}
    </group>
  );
}

/** A running crew's hull is solid; a coasting one is present but recessive. */
const HULL_OPACITY = { running: 0.96, coasting: 0.45 } as const;

/** The three materials a hull wears that depend only on running/coasting. */
interface HullPaint {
  hull: THREE.ShaderMaterial;
  canopy: THREE.MeshBasicMaterial;
  nozzle: THREE.MeshBasicMaterial;
}

function Orbiter({
  orbiter,
  starRadius,
  index,
  paint,
}: {
  orbiter: SceneOrbiter;
  starRadius: number;
  index: number;
  paint: HullPaint;
}) {
  const reduceMotion = useReduceMotion();
  const carousel = useRef<THREE.Group>(null);
  const light = useRef<THREE.Mesh>(null);
  const halo = useRef<THREE.Mesh>(null);
  const port = useRef<THREE.Mesh>(null);
  const starboard = useRef<THREE.Mesh>(null);
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
      navOffset: rand() * 9,
    };
  }, [orbiter.id, index]);

  /*
   * The lamps and the burn: the only materials that are genuinely per ship,
   * because each one's opacity is animated on its own phase below. Built here
   * and disposed here — the meshes that wear them carry `dispose={null}` for
   * the sake of the shared geometry (`shipSurface.ts`), which switches off
   * r3f's own disposal for the material too.
   */
  const lamps = useMemo(() => {
    const glow = (color: string, opacity: number, additive: boolean, side?: THREE.Side) =>
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity,
        depthWrite: false,
        ...(additive ? { blending: THREE.AdditiveBlending } : {}),
        ...(side !== undefined ? { side } : {}),
      });
    return {
      beacon: glow(GL.starlight, 0.12, false),
      bloom: glow(GL.starlight, 0, true),
      port: glow(GL_NAV.port, 0.42, true),
      starboard: glow(GL_NAV.starboard, 0.42, true),
      throat: glow(GL.ion, 0, true),
      plume: glow(GL.ion, 0, true, THREE.DoubleSide),
    };
  }, []);
  useEffect(
    () => () => {
      for (const material of Object.values(lamps)) material.dispose();
    },
    [lamps],
  );

  /** Seconds this craft has been flying, accumulated locally — see the frame
   *  callback below for why not `clock.elapsedTime`. */
  const clockRef = useRef(0);

  useFrame((_state, raw) => {
    // Bounded like every other time-integrated animation: an unclamped
    // `delta` is wall-clock, so one stalled frame jumps this forward by the
    // whole stall (`CameraRig`'s `MAX_FRAME_SECONDS`).
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    /*
     * **Local time, not `clock.elapsedTime`.** r3f zeroes the clock on *every*
     * `frameloop` transition, so anything reading it as monotonic jumps when the
     * loop parks and restarts.
     *
     * Worth knowing what this does and does not buy. It keeps the phases below
     * — engine flicker, beacon, strobe — continuous across a frameloop
     * transition, but it cannot survive this component unmounting, because
     * `clockRef` dies with it. Ships live in the *swapped* scene content, so the
     * teardown they used to face on a route without a constellation reset them
     * anyway. Nothing tears the scene down now (`SkyBackdrop`), which is what
     * actually made this defence hold.
     */
    clockRef.current += delta;
    const elapsed = clockRef.current;
    // **The orbit itself is unconditional.** A cage is up there whether or not
    // anyone is running and whether or not the box is plugged in, and freezing
    // the fleet to say so made a rig of disconnected boxes look like a still
    // image. Hardware state is the *star's* to report now — an undetected box
    // burns its star down (`StellarSurface`'s `dim`) — which leaves the ships
    // free to just be ships. `active` still owns the engine and the strobe
    // below: a coasting craft with a cold engine is exactly right for a crew
    // that is assigned but not running.
    const spin = carousel.current;
    if (spin && !reduceMotion) {
      // A coasting crew still travels, just slowly — the speed difference is
      // what carries "running" now that stopping altogether is off the table.
      spin.rotation.y +=
        delta * params.speed * (orbiter.active ? 1 : COASTING_SPEED);
    }

    // The engine: a nervous ion flicker while under way, cold when parked.
    const burn = exhaust.current;
    if (burn) {
      let level = 0;
      if (orbiter.active && !reduceMotion) {
        const t = elapsed + params.burnOffset;
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

    /*
     * The lights. **Every ship keeps its beacon**, running or not — a dark
     * satellite reads as debris, and a parked crew is still a crew. `active`
     * scales their brightness rather than switching them off, so a running ship
     * is the brightest thing in the belt without a coasting one being dead.
     */
    const level = orbiter.active ? 1 : COASTING_LIGHTS;
    const t = elapsed;

    // Anti-collision beacon: the sharp double-flash, plus an additive bloom
    // that flares wider than the lamp itself — that second element is what
    // makes it read as *light emitted* rather than a white dot changing
    // opacity, and it is the whole difference between the two.
    const beacon = light.current;
    const bloom = halo.current;
    if (beacon) {
      const phase = (t + params.blinkOffset) % params.blinkPeriod;
      const flash = reduceMotion
        ? 0.55 // no strobing under reduced motion — a steady lamp instead
        : strobe(phase, 0, FLASH_SECONDS) +
          SECOND_FLASH_PEAK * strobe(phase, SECOND_FLASH_AT, FLASH_SECONDS);
      (beacon.material as THREE.MeshBasicMaterial).opacity =
        (0.12 + flash * 0.88) * level;
      beacon.scale.setScalar(1 + flash * 0.9);
      if (bloom) {
        (bloom.material as THREE.MeshBasicMaterial).opacity =
          flash * 0.45 * level;
        bloom.scale.setScalar(0.7 + flash * 2.1);
      }
    }

    // Port and starboard: steady lamps with a slow swell, deliberately *not*
    // blinking. Aviation runs its nav lights steady and strobes only the
    // beacon, and it is also the calmer choice — a rig can carry a dozen ships
    // at once, and three blinkers apiece would be a disco rather than an
    // instrument. Half a period apart so the hull breathes side to side.
    const breathe = (offset: number) =>
      reduceMotion ? 0.5 : 0.5 + 0.5 * Math.sin((t + offset) * BREATHE_RATE);
    const portLamp = port.current;
    if (portLamp) {
      (portLamp.material as THREE.MeshBasicMaterial).opacity =
        (0.42 + 0.34 * breathe(params.navOffset)) * level;
    }
    const starboardLamp = starboard.current;
    if (starboardLamp) {
      (starboardLamp.material as THREE.MeshBasicMaterial).opacity =
        (0.42 + 0.34 * breathe(params.navOffset + Math.PI / BREATHE_RATE)) *
        level;
    }
  });

  const orbitRadius = starRadius * params.reach;

  return (
    <group rotation={params.tilt}>
      <group ref={carousel} rotation={[0, params.bearing, 0]}>
        <group position={[orbitRadius, 0, 0]}>
          {/* The craft is modelled at `starRadius = 1` and scaled here, so every
              ship in the app shares one set of buffers (`shipSurface.ts`). */}
          <group scale={starRadius}>
            {/* Nose into the direction of travel: the carousel spins +y, which
                moves a craft at +x toward −z. */}
            <ShipHull paint={paint} lamps={lamps} exhaust={exhaust} />

            {/* The anti-collision beacon on the spine: the lamp itself, plus an
                additive bloom around it that only exists while the strobe
                fires. Neither writes depth, so neither punches a hole in the
                hull it sits on. */}
            <mesh
              ref={light}
              position={[0, 0.12, 0.02]}
              geometry={SHIP_GEOMETRY.beacon}
              material={lamps.beacon}
              dispose={null}
            />
            <mesh
              ref={halo}
              position={[0, 0.12, 0.02]}
              geometry={SHIP_GEOMETRY.bloom}
              material={lamps.bloom}
              dispose={null}
            />

            {/* Navigation lights (`constellationStyle.ts`'s `GL_NAV`): port red
                to the left of travel, starboard green to the right. The nose
                points −z and up is +y, so left is −x. Smaller than the beacon —
                they mark the hull's extent, they don't announce it. */}
            <mesh
              ref={port}
              position={[-0.088, 0, 0.03]}
              geometry={SHIP_GEOMETRY.lamp}
              material={lamps.port}
              dispose={null}
            />
            <mesh
              ref={starboard}
              position={[0.088, 0, 0.03]}
              geometry={SHIP_GEOMETRY.lamp}
              material={lamps.starboard}
              dispose={null}
            />
          </group>

          {/* The mini tag. DOM, like the nameplates, so it stays crisp — but a
              step smaller and fainter: this labels an annotation, and it must
              never outrank the star's own plate.

              Skipped entirely when the crew has nobody left in orbit (a solo
              animal, running, is at the star): `Html` mounts a real DOM overlay
              per instance and keeps it positioned every frame, so an empty one
              is a cost paid for nothing on every star in the rig. */}
          {orbiter.name !== "" && (
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
                  textShadow:
                    "0 0 4px var(--color-void), 0 0 2px var(--color-void)",
                }}
              >
                {orbiter.name}
              </span>
            </Html>
          )}
        </group>
      </group>
    </group>
  );
}

/**
 * The craft itself, nose toward −z, at unit scale — the caller scales it to
 * its star, so the whole ship spans roughly the old octahedron's footprint. It
 * must stay an annotation, never a second star.
 *
 * Hull and fins wear `shipSurface.ts`'s star-lit material; its Halo floor keeps
 * the night side legible instead of vanishing. Canopy and nozzle stay
 * basic-material accents, and the exhaust is the one additive element — an ion
 * drive's glow, in Ion, animated by the parent.
 */
function ShipHull({
  paint,
  lamps,
  exhaust,
}: {
  paint: HullPaint;
  lamps: { throat: THREE.MeshBasicMaterial; plume: THREE.MeshBasicMaterial };
  exhaust: React.RefObject<THREE.Group | null>;
}) {
  return (
    <group>
      {/* Fuselage: a capsule laid along z. */}
      <mesh
        rotation={[Math.PI / 2, 0, 0]}
        geometry={SHIP_GEOMETRY.fuselage}
        material={paint.hull}
        dispose={null}
      />

      {/* Canopy: a small blister forward of midships. */}
      <mesh
        position={[0, 0.045, -0.06]}
        geometry={SHIP_GEOMETRY.canopy}
        material={paint.canopy}
        dispose={null}
      />

      {/* Fins: two swept side planes and a tail, at the stern. */}
      {FINS.map((fin, i) => (
        <mesh
          key={i}
          position={fin.position}
          rotation={fin.rotation}
          geometry={SHIP_GEOMETRY.fin}
          material={paint.hull}
          dispose={null}
        />
      ))}

      {/* Engine nozzle, flaring aft. */}
      <mesh
        position={[0, 0, 0.17]}
        rotation={[Math.PI / 2, 0, 0]}
        geometry={SHIP_GEOMETRY.nozzle}
        material={paint.nozzle}
        dispose={null}
      />

      {/* The burn: throat glow plus a tapering plume, additive so it reads as
          light. Opacity is driven per-frame by the parent; `peak` is each
          part's ceiling so throat and plume flicker in ratio. */}
      <group ref={exhaust} visible={false}>
        <mesh
          position={[0, 0, 0.2]}
          userData={{ peak: 1 }}
          geometry={SHIP_GEOMETRY.throat}
          material={lamps.throat}
          dispose={null}
        />
        {/* +90° about x points the cone's apex aft, so the plume tapers away
            from the nozzle. */}
        <mesh
          position={[0, 0, 0.29]}
          rotation={[Math.PI / 2, 0, 0]}
          userData={{ peak: 0.45 }}
          geometry={SHIP_GEOMETRY.plume}
          material={lamps.plume}
          dispose={null}
        />
      </group>
    </group>
  );
}

const FINS: { position: [number, number, number]; rotation: [number, number, number] }[] = [
  { position: [0.085, 0, 0.08], rotation: [0, -0.35, 0] },
  { position: [-0.085, 0, 0.08], rotation: [0, 0.35, 0] },
  { position: [0, 0.085, 0.08], rotation: [0, 0, Math.PI / 2] },
];

/**
 * Sharp attack, **quadratic** falloff — the shape of a xenon strobe, not a
 * sine. The square is the polish: a linear decay reads as a lamp being turned
 * down, where a real flash dumps most of its light in the first instant and
 * trails off. Same peak, same duration, entirely different character.
 */
function strobe(phase: number, start: number, width: number): number {
  if (phase < start || phase > start + width) return 0;
  const k = 1 - (phase - start) / width;
  return k * k;
}
