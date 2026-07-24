import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { linkStars, placeStars, type Star } from "@/lib/sessions/stars";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The 3D constellation (`starting-a-session.md` §6).
 *
 * One star per animal in the cohort. Stars whose box is `IN_SESSION` are lit
 * and clickable; everyone else is present but dim and inert (§6.2) — including
 * animals in a group that isn't running and animals with no box at all.
 */

export interface ConstellationAnimal {
  animalId: string;
  name: string;
  /** True only while that animal's box is actually `IN_SESSION`. */
  lit: boolean;
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

      {stars.map((star) => (
        <StarNode
          key={star.animalId}
          star={star}
          lit={lit.has(star.animalId)}
          focused={focusedId === star.animalId}
          onSelect={() => onFocus(star.animalId)}
        />
      ))}

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
  focused,
  onSelect,
}: {
  star: Star;
  lit: boolean;
  focused: boolean;
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    if (!hovered) return;
    document.body.style.cursor = "pointer";
    return () => {
      document.body.style.cursor = "";
    };
  }, [hovered]);

  const scale = lit && hovered ? 1.5 : 1;

  return (
    <group position={star.position}>
      {/* Purely visual — all interaction lives on the hit sphere below, which
          only exists for a lit star, so an unlit one is inert by construction
          rather than by a disabled handler (§6.2). */}
      <mesh scale={scale}>
        <sphereGeometry args={[star.radius, 20, 20]} />
        {/* Basic (unlit) material keeps the palette matte — a lit material
            would introduce the highlights and falloff §2.2 rules out. */}
        <meshBasicMaterial
          color={lit ? GL.ion : GL.pulsar}
          transparent
          opacity={lit ? 1 : 0.34}
        />
      </mesh>

      {/* A wider invisible hit area — a 0.2-unit sphere is a hard click target
          at overview distance. */}
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

      {focused && <ArrivalRings radius={star.radius} />}
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
