import { Billboard, Html, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import {
  CORONA_FRAGMENT,
  CORONA_VERTEX,
  STAR_FRAGMENT,
  STAR_VERTEX,
  rampColors,
  temperatureFor,
} from "./starSurface";
import { linkStars, placeStars, type Star } from "@/lib/sessions/stars";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The 3D constellation (`starting-a-session.md` §6).
 *
 * One star per animal in the cohort. Stars whose box is `IN_SESSION` are lit
 * and clickable; everyone else is present but dim and inert (§6.2) — including
 * animals in a group that isn't running and animals with no box at all.
 *
 * A lit star renders as an actual stellar surface, and its **temperature is
 * that animal's pooled rolling accuracy** (§6.2, `starSurface.ts`): red at
 * chance through orange and yellow to blue-white as it works. That makes the
 * overview answer "who is doing well" without opening a panel.
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

/** Where the camera sits when nothing is focused. */
const OVERVIEW_POSITION = new THREE.Vector3(0, 4, 18);
const OVERVIEW_TARGET = new THREE.Vector3(0, 0, 0);
/** How far from a star the camera settles on arrival. */
const ARRIVAL_DISTANCE = 3.6;
/**
 * How far to aim past the star, so it lands left of centre instead of behind
 * the panel docked to the right (§6.3/§6.4).
 */
const PANEL_OFFSET = 1.15;
/** §6.3 — the fly takes this long; short enough not to feel like waiting. */
const FLIGHT_SECONDS = 1.5;

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
  const stars = useMemo(
    () => placeStars(cohortId, animals.map((a) => a.animalId)),
    [cohortId, animals],
  );
  const links = useMemo(() => linkStars(stars), [stars]);
  const lit = useMemo(
    () => new Set(animals.filter((a) => a.lit).map((a) => a.animalId)),
    [animals],
  );
  const accuracy = useMemo(
    () => new Map(animals.map((a) => [a.animalId, a.accuracy ?? null])),
    [animals],
  );
  const byId = useMemo(
    () => new Map(animals.map((a) => [a.animalId, a])),
    [animals],
  );

  return (
    <Canvas
      camera={{ position: OVERVIEW_POSITION.toArray(), fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true }}
      style={{ background: GL.void }}
    >
      <CameraRig stars={stars} focusedId={focusedId} />

      {links.map(([a, b]) => (
        <Link
          key={`${a}-${b}`}
          from={stars[a]!.position}
          to={stars[b]!.position}
          live={lit.has(stars[a]!.animalId) && lit.has(stars[b]!.animalId)}
        />
      ))}

      {stars.map((star) => {
        const animal = byId.get(star.animalId);
        return (
          <StarNode
            key={star.animalId}
            star={star}
            lit={lit.has(star.animalId)}
            name={animal?.name ?? ""}
            box={animal?.box ?? null}
            accuracy={accuracy.get(star.animalId) ?? null}
            focused={focusedId === star.animalId}
            onSelect={() => onFocus(star.animalId)}
          />
        );
      })}

      {/* Click-through on empty space returns to the overview, which is the
          gesture people try before finding the Back control. */}
      <mesh onPointerMissed={() => onFocus(null)} visible={false}>
        <boxGeometry args={[0.01, 0.01, 0.01]} />
      </mesh>

      <OrbitControls
        makeDefault
        enablePan={false}
        enableZoom
        minDistance={1.5}
        maxDistance={40}
        enabled={focusedId === null}
      />
    </Canvas>
  );
}

/**
 * §6.3 — the eased cinematic move, and the one acknowledged exception to the
 * app's spring-physics convention: a camera flythrough reads as cinematic
 * rather than mechanical, and a spring would fight that.
 */
function CameraRig({ stars, focusedId }: { stars: Star[]; focusedId: string | null }) {
  const { camera, controls } = useThree();
  const reduceMotion = useReduceMotion();

  const flight = useRef<{
    fromPosition: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toPosition: THREE.Vector3;
    toTarget: THREE.Vector3;
    elapsed: number;
  } | null>(null);
  const target = useRef(OVERVIEW_TARGET.clone());

  useEffect(() => {
    const star = stars.find((s) => s.animalId === focusedId);
    const starPoint = star ? new THREE.Vector3(...star.position) : null;

    // Approach along the current view direction, so the move never swings the
    // constellation around behind the camera.
    const approach = starPoint
      ? camera.position.clone().sub(starPoint).normalize()
      : null;
    const toPosition =
      starPoint && approach
        ? starPoint.clone().add(approach.clone().multiplyScalar(ARRIVAL_DISTANCE))
        : OVERVIEW_POSITION.clone();

    // Aim past the star, to its right — which puts the star itself on the left
    // of the frame, clear of the docked panel.
    const toTarget = starPoint ? starPoint.clone() : OVERVIEW_TARGET.clone();
    if (starPoint && approach) {
      const right = new THREE.Vector3()
        .crossVectors(camera.up, approach)
        .normalize()
        .multiplyScalar(PANEL_OFFSET);
      toTarget.add(right);
    }

    if (reduceMotion) {
      camera.position.copy(toPosition);
      target.current.copy(toTarget);
      camera.lookAt(toTarget);
      return;
    }

    flight.current = {
      fromPosition: camera.position.clone(),
      fromTarget: target.current.clone(),
      toPosition,
      toTarget,
      elapsed: 0,
    };
  }, [focusedId, stars, camera, reduceMotion]);

  useFrame((_state, delta) => {
    const move = flight.current;
    if (!move) return;

    move.elapsed += delta;
    const t = Math.min(1, move.elapsed / FLIGHT_SECONDS);
    const eased = 1 - (1 - t) ** 3; // cubic ease-out

    camera.position.lerpVectors(move.fromPosition, move.toPosition, eased);
    target.current.lerpVectors(move.fromTarget, move.toTarget, eased);
    camera.lookAt(target.current);

    if (t >= 1) {
      flight.current = null;
      // Hand the orbit controls the target we arrived at, so re-enabling them
      // doesn't snap the view back to the origin.
      const orbit = controls as unknown as { target?: THREE.Vector3; update?: () => void };
      orbit?.target?.copy(target.current);
      orbit?.update?.();
    }
  });

  return null;
}

function StarNode({
  star,
  lit,
  name,
  box,
  accuracy,
  focused,
  onSelect,
}: {
  star: Star;
  lit: boolean;
  name: string;
  box: number | null;
  accuracy: number | null;
  focused: boolean;
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const visual = useRef<THREE.Group>(null);
  const reduceMotion = useReduceMotion();

  useEffect(() => {
    if (!hovered) return;
    document.body.style.cursor = "pointer";
    return () => {
      document.body.style.cursor = "";
    };
  }, [hovered]);

  // The swell is eased rather than snapped — a star that jumps size on
  // pointer-over reads as a glitch, and the cursor crossing a 4×-radius hit
  // sphere makes that jump frequent. Frame-rate independent, so it feels the
  // same on a 60Hz lab monitor as on a 144Hz one.
  const target = lit && hovered ? 1.5 : 1;
  useFrame((_state, delta) => {
    const group = visual.current;
    if (!group) return;
    if (reduceMotion) {
      group.scale.setScalar(target);
      return;
    }
    const k = 1 - Math.exp(-delta * 14);
    group.scale.lerp(SCALE_TARGET.setScalar(target), k);
  });

  return (
    <group position={star.position}>
      <group ref={visual}>
        {lit ? (
          <StellarSurface radius={star.radius} accuracy={accuracy} />
        ) : (
          // An unlit star stays a flat matte dot — it has no performance to
          // report, and giving it a surface would imply it were running (§6.2).
          <mesh>
            <sphereGeometry args={[star.radius, 20, 20]} />
            <meshBasicMaterial color={GL.pulsar} transparent opacity={0.34} />
          </mesh>
        )}
      </group>

      {/* A wider invisible hit area — a 0.2-unit sphere is a hard click target
          at overview distance. All interaction lives here, and it only exists
          for a lit star, so an unlit one is inert by construction rather than
          by a disabled handler (§6.2). */}
      {lit && (
        <mesh
          visible={false}
          onClick={onSelect}
          onPointerOver={() => setHovered(true)}
          onPointerOut={() => setHovered(false)}
        >
          <sphereGeometry args={[star.radius * 4, 8, 8]} />
        </mesh>
      )}

      {lit && <HoverReticle radius={star.radius} active={hovered && !focused} />}

      {/* Persistent, because "which star is which" is a question the overview
          should never make you hover to answer. Only lit stars get one: a
          plate on every animal in the cohort would bury the running ones. */}
      {lit && <Nameplate name={name} box={box} radius={star.radius} hovered={hovered} />}

      {focused && <ArrivalRings radius={star.radius} />}
    </group>
  );
}

/** Scratch vector for the hover lerp — allocating one per frame per star adds
 *  up to real garbage at 60fps × six stars. */
const SCALE_TARGET = new THREE.Vector3();

/**
 * The hover treatment: a billboarded targeting reticle — four short arcs at
 * the quadrants, the way an instrument marks the thing it is tracking.
 *
 * Deliberately *not* another full ring: `ArrivalRings` already owns concentric
 * rings for the focused state, and two ring treatments a few frames apart
 * would read as one confused animation. Billboarded so it faces the camera
 * from any orbit angle, which a flat ring in the XY plane does not.
 */
function HoverReticle({ radius, active }: { radius: number; active: boolean }) {
  const group = useRef<THREE.Group>(null);
  const materials = useRef<THREE.MeshBasicMaterial[]>([]);
  const reduceMotion = useReduceMotion();

  useFrame((_state, delta) => {
    const g = group.current;
    if (!g) return;
    const k = reduceMotion ? 1 : 1 - Math.exp(-delta * 16);
    // Sweeps inward as it appears — the arcs closing on the star is what makes
    // it read as acquiring a target rather than merely fading in.
    const scaleTo = active ? 1 : 1.35;
    g.scale.lerp(SCALE_TARGET.setScalar(scaleTo), k);
    const opacityTo = active ? 0.9 : 0;
    for (const material of materials.current) {
      if (material) material.opacity += (opacityTo - material.opacity) * k;
    }
  });

  return (
    <Billboard>
      <group ref={group}>
        {[0, 1, 2, 3].map((quadrant) => (
          <mesh key={quadrant} rotation={[0, 0, (quadrant * Math.PI) / 2]}>
            {/* A short arc centred on its quadrant, with a hair of thickness —
                thin enough to stay an annotation at overview distance. */}
            <ringGeometry
              args={[radius * 2.1, radius * 2.1 + 0.02, 24, 1, -Math.PI / 12, Math.PI / 6]}
            />
            <meshBasicMaterial
              ref={(material) => {
                if (material) materials.current[quadrant] = material;
              }}
              color={GL.pulsar}
              transparent
              opacity={0}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ))}
      </group>
    </Billboard>
  );
}

/**
 * The running animal's callout: box number and name on a small matte plate,
 * hung under its star with a short leader.
 *
 * Rendered as DOM rather than in-scene text, so it stays crisp and uses the
 * app's own type (JetBrains Mono — this is an identifier, §2.3). No
 * `distanceFactor`: a plate that grew as the camera closed in would be
 * enormous on arrival at a star. Constant screen size is also what makes it a
 * HUD annotation rather than a floating object in the scene.
 */
function Nameplate({
  name,
  box,
  radius,
  hovered,
}: {
  name: string;
  box: number | null;
  radius: number;
  hovered: boolean;
}) {
  return (
    <Html
      center
      position={[0, -(radius * 3.5), 0]}
      // Never steals the pointer from the star's hit sphere behind it.
      style={{ pointerEvents: "none", userSelect: "none" }}
      zIndexRange={[10, 0]}
    >
      <div className="flex flex-col items-center">
        <span
          className="w-px transition-colors duration-200"
          style={{
            height: 9,
            background: hovered ? "var(--color-pulsar)" : "var(--color-halo)",
          }}
        />
        <span
          className="flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-[1px] transition-colors duration-200"
          style={{
            borderColor: hovered ? "var(--color-pulsar)" : "var(--color-halo)",
            background: "color-mix(in srgb, var(--color-void) 82%, transparent)",
          }}
        >
          {box !== null && (
            <span className="font-mono text-[9px] leading-none text-pulsar">{box}</span>
          )}
          <span className="font-mono text-[10px] leading-none text-starlight">{name}</span>
        </span>
      </div>
    </Html>
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

/**
 * §6.3's arrival treatment — thin concentric rings that animate outward and
 * settle into a slowly rotating decorative ring. An instrument/HUD read rather
 * than a glow, which §2.2 forbids outright.
 *
 * Flagged in the doc as proposed-and-worth-seeing-built: this is the simplest
 * version of it, deliberately.
 */
function ArrivalRings({ radius }: { radius: number }) {
  const group = useRef<THREE.Group>(null);
  const rings = useRef<THREE.Mesh[]>([]);
  const elapsed = useRef(0);
  const reduceMotion = useReduceMotion();

  useFrame((_state, delta) => {
    if (reduceMotion) return;
    elapsed.current += delta;
    if (group.current) group.current.rotation.z += delta * 0.25;

    rings.current.forEach((ring, index) => {
      if (!ring) return;
      // Each ring expands from the star and settles, staggered.
      const t = Math.min(1, Math.max(0, (elapsed.current - index * 0.18) / 0.9));
      const eased = 1 - (1 - t) ** 3;
      ring.scale.setScalar(0.25 + eased * 0.75);
      const material = ring.material as THREE.MeshBasicMaterial;
      material.opacity = 0.5 * eased;
    });
  });

  return (
    <group ref={group} rotation={[Math.PI / 2.6, 0, 0]}>
      {[2.6, 3.6, 4.8].map((scale, index) => (
        <mesh
          key={scale}
          ref={(mesh) => {
            if (mesh) rings.current[index] = mesh;
          }}
        >
          <ringGeometry args={[radius * scale, radius * scale + 0.012, 96]} />
          <meshBasicMaterial
            color={index === 1 ? GL.pulsar : GL.halo}
            transparent
            opacity={0}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

function Link({
  from,
  to,
  live,
}: {
  from: [number, number, number];
  to: [number, number, number];
  live: boolean;
}) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([...from, ...to], 3),
    );
    return g;
  }, [from, to]);

  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <line>
      <primitive object={geometry} attach="geometry" />
      <lineBasicMaterial
        color={GL.pulsar}
        transparent
        opacity={live ? 0.55 : 0.1}
      />
    </line>
  );
}
