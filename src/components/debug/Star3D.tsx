import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import type { BoxHealth } from "@/components/chrome/ConstellationStatus";
import { GL } from "@/components/chrome/constellationStyle";
import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The node detail view's 3D star (ephymeris_v1.0.md §4.3).
 *
 * Same visual family as Mission Control's constellation (`Constellation3D`),
 * same rules: matte basic materials only — no lit shading, no glow (§2.2) —
 * and motion that reads as an instrument, not a light show. The faceted core
 * is tinted by the box's health; a wireframe shell makes the slow rotation
 * visible on an otherwise flat sphere; a detected box has a mote in orbit,
 * mirroring the landing constellation's grammar; tilted rings echo §6.3's
 * arrival treatment.
 */

const CORE_COLOR: Record<BoxHealth, string> = {
  nominal: GL.ion,
  idle: GL.pulsar,
  absent: GL.halo,
  fault: "#c96c6c", // --color-status-error's literal, matte
};

export function Star3D({ health }: { health: BoxHealth }) {
  return (
    <Canvas
      camera={{ position: [0, 0.6, 5.2], fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true }}
      style={{ background: GL.void }}
    >
      <Backdrop />
      <StarBody health={health} />
    </Canvas>
  );
}

function StarBody({ health }: { health: BoxHealth }) {
  const reduceMotion = useReduceMotion();
  const core = useRef<THREE.Group>(null);
  const shell = useRef<THREE.Mesh>(null);
  const rings = useRef<THREE.Group>(null);
  const mote = useRef<THREE.Group>(null);
  const detected = health === "nominal" || health === "idle";

  useFrame((state, delta) => {
    if (reduceMotion) return;
    if (core.current) {
      core.current.rotation.y += delta * 0.18;
      // A slow bob, small enough to read as drift rather than bouncing.
      core.current.position.y = Math.sin(state.clock.elapsedTime * 0.5) * 0.08;
    }
    if (shell.current) {
      shell.current.rotation.y -= delta * 0.07;
      shell.current.rotation.x += delta * 0.03;
    }
    if (rings.current) rings.current.rotation.z += delta * 0.12;
    if (mote.current) mote.current.rotation.y += delta * (health === "nominal" ? 0.9 : 0.45);
  });

  return (
    <group>
      <group ref={core}>
        {/* Faceted matte core — flat triangles catch nothing, exactly right. */}
        <mesh>
          <icosahedronGeometry args={[1, 1]} />
          <meshBasicMaterial color={CORE_COLOR[health]} />
        </mesh>
        {/* Wireframe one step outside the surface, so rotation is legible. */}
        <mesh ref={shell} scale={1.18}>
          <icosahedronGeometry args={[1, 1]} />
          <meshBasicMaterial color={GL.starlight} wireframe transparent opacity={0.14} />
        </mesh>
      </group>

      {/* §6.3's instrument rings, persistent and slowly turning. */}
      <group ref={rings} rotation={[Math.PI / 2.4, 0, 0]}>
        {[1.7, 2.15].map((radius, index) => (
          <mesh key={radius}>
            <ringGeometry args={[radius, radius + 0.012, 96]} />
            <meshBasicMaterial
              color={index === 0 ? GL.pulsar : GL.halo}
              transparent
              opacity={index === 0 ? 0.45 : 0.3}
              side={THREE.DoubleSide}
            />
          </mesh>
        ))}
      </group>

      {/* The orbiting mote — same grammar as the landing view: present only
          when the board is actually on the bus. */}
      {detected && (
        <group ref={mote} rotation={[0.4, 0, 0.15]}>
          <mesh position={[1.95, 0, 0]}>
            <sphereGeometry args={[0.055, 12, 12]} />
            <meshBasicMaterial color={GL.starlight} />
          </mesh>
        </group>
      )}
    </group>
  );
}

/** A sparse, static distant field — depth without competing for attention. */
function Backdrop() {
  const geometry = useMemo(() => {
    const rand = mulberry32(0x57a2f1e1d);
    const positions = new Float32Array(140 * 3);
    for (let i = 0; i < 140; i += 1) {
      // Points on a far shell, biased behind the star.
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const radius = 16 + rand() * 8;
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta) * 0.6;
      positions[i * 3 + 2] = -Math.abs(radius * Math.cos(phi)) - 4;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return g;
  }, []);

  return (
    <points>
      <primitive object={geometry} attach="geometry" />
      <pointsMaterial color={GL.starlight} size={0.06} transparent opacity={0.5} sizeAttenuation />
    </points>
  );
}
