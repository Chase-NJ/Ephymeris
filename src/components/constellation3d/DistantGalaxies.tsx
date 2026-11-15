import { Billboard } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { mulberry32 } from "@/lib/prng";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { makeFarSpriteMaterial } from "./farMaterials";
import { makeEllipticalTexture, makeSpiralTexture } from "./skyTextures";

/**
 * Other galaxies, far off — a dozen small sprites in the sky at infinity
 * (`FarSky.tsx`), each a painted spiral or elliptical at its own roll and
 * squash.
 *
 * They are what makes the home galaxy a galaxy *among* galaxies rather than
 * the whole sky: small, faint, and unmistakably the same kind of thing as the
 * band overhead. Billboards, because at this distance a galaxy has no
 * parallax worth drawing and a sprite is one quad.
 *
 * Each rolls very slowly about its own axis — a spiral's arms creep — so a
 * long look catches motion. Held when `still`.
 */
export function DistantGalaxies({ seed, still }: { seed: number; still: boolean }) {
  const meshes = useRef<THREE.Mesh[]>([]);

  const { textures, placements, materials } = useMemo(() => {
    const made = [
      makeSpiralTexture(seed ^ 0x11, "#b9c4ff", 2, 0.22),
      makeSpiralTexture(seed ^ 0x12, "#d7c4ff", 3, 0.17),
      makeSpiralTexture(seed ^ 0x13, "#c4e5e0", 2, 0.28),
      makeEllipticalTexture(seed ^ 0x14, "#e8d6c0"),
      makeEllipticalTexture(seed ^ 0x15, "#d4c6e6"),
    ];
    const rand = mulberry32(seed ^ 0x77);
    const placed = Array.from({ length: GALAXY_SIGHTINGS }, (_, i) => {
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const r = SHELL_NEAR + rand() * (SHELL_FAR - SHELL_NEAR);
      return {
        position: [
          Math.sin(phi) * Math.cos(theta) * r,
          Math.cos(phi) * r * 0.8,
          Math.sin(phi) * Math.sin(theta) * r,
        ] as [number, number, number],
        // Mostly small; one or two near enough to show arms.
        scale: rand() > 0.85 ? 18 + rand() * 12 : 5 + rand() * 8,
        squash: 0.35 + rand() * 0.65, // inclination, as a flattening
        roll: rand() * Math.PI * 2,
        spin: (rand() - 0.5) * 0.02,
        opacity: 0.4 + rand() * 0.35,
        textureIndex: i % made.length,
      };
    });
    const materials = placed.map((p) =>
      makeFarSpriteMaterial(made[p.textureIndex]!, p.opacity, { additive: true }),
    );
    return { textures: made, placements: placed, materials };
  }, [seed]);

  useEffect(() => () => {
    textures.forEach((t) => t.dispose());
    materials.forEach((m) => m.dispose());
  }, [textures, materials]);

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (still) return;
    placements.forEach((p, i) => {
      const mesh = meshes.current[i];
      if (mesh) mesh.rotation.z += delta * p.spin;
    });
  });

  return (
    <group>
      {placements.map((p, i) => (
        <Billboard key={i} position={p.position}>
          <mesh
            ref={(mesh) => {
              if (mesh) meshes.current[i] = mesh;
            }}
            rotation={[0, 0, p.roll]}
            scale={[p.scale, p.scale * p.squash, 1]}
            renderOrder={-9}
            material={materials[i]!}
          >
            <planeGeometry args={[1, 1]} />
          </mesh>
        </Billboard>
      ))}
    </group>
  );
}

const GALAXY_SIGHTINGS = 12;
/** Distance from the camera. Immaterial to depth (they are drawn at the far
 *  plane), but it sets their scale against the home galaxy. */
const SHELL_NEAR = 138;
const SHELL_FAR = 160;
