import { Billboard } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { DistantGalaxies } from "./DistantGalaxies";
import { HomeGalaxy } from "./HomeGalaxy";
import { SkyEvents } from "./SkyEvents";
import { makeNebulaTexture } from "./skyTextures";

/**
 * The deep-sky backdrop behind every route: the galaxy we orbit, filling a
 * third of the frame; other galaxies far off; nebula banks; two layers of
 * stars; and the things that happen — meteors, supernovae, the odd comet.
 *
 * It used to be a star field, a few clouds and a flash every half minute, and
 * it read as wallpaper. What makes a sky a *place* is that it has a shape you
 * can hold (the home galaxy's bulge and arms), depth you can feel (near stars
 * over far ones over clouds over other galaxies), and time passing (the whole
 * thing drifts, the disc turns, and events arrive on their own schedule). None
 * of that needs to be expensive: the sky is five point-cloud draws and a few
 * dozen sprites, every texture painted once, and the only per-frame work is a
 * handful of rotations and time uniforms.
 *
 * Everything here is scenery, and scenery in this app obeys two rules. It is
 * **deterministic** — every position, hue, phase and event is seeded through
 * `mulberry32`, so the sky is the same sky on every mount and every machine
 * (the same contract the 2D `Starfield` and the cohort worlds honour). And it
 * is **behind the data**: nothing lives inside the camera's `maxDistance`,
 * everything renders at low opacity with `depthWrite` off and a negative
 * `renderOrder`, so no piece of scenery ever occludes or competes with a star
 * or a world an operator is reading.
 *
 * Under reduced motion the whole backdrop holds still: the twinkle freezes at
 * its seeded phase, nothing drifts or turns, and no event fires — the field
 * stays, the theatre goes.
 */

/** Backdrop stars live on this shell — outside `maxDistance` (40), so the
 *  camera can never dolly through the sky. */
const FIELD_NEAR = 58;
const FIELD_FAR = 92;
const FIELD_COUNT = 1400;

/** The dust layer: many more, far fainter, squeezed toward the home galaxy's
 *  plane — the haze between us and it that makes the disc read as a hundred
 *  billion stars rather than four thousand points. */
const DUST_COUNT = 2600;

/** Nebulae sit behind the stars, so points twinkle *in front* of the clouds. */
const NEBULA_NEAR = 100;
const NEBULA_FAR = 135;

/** One backdrop seed — change it and a different (equally permanent) sky. */
const SKY_SEED = 0xa57e21;

/** The whole sky's slow drift, radians per second about the vertical. About a
 *  degree a minute: nothing you see happen, everything you notice has
 *  happened. */
const SKY_DRIFT = 0.0003;

export function SceneBackdrop() {
  const reduceMotion = useReduceMotion();
  const sky = useRef<THREE.Group>(null);

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (reduceMotion || !sky.current) return;
    sky.current.rotation.y += delta * SKY_DRIFT;
  });

  return (
    <group ref={sky}>
      <DistantGalaxies seed={SKY_SEED} />
      <NebulaField />
      <HomeGalaxy seed={SKY_SEED ^ 0x41} />
      <DustBand />
      <TwinkleField />
      <SkyEvents seed={SKY_SEED} shellNear={FIELD_NEAR} shellFar={FIELD_FAR} />
    </group>
  );
}

// --- twinkling stars --------------------------------------------------------

const TWINKLE_VERTEX = /* glsl */ `
  attribute float aSize;
  attribute float aPhase;
  attribute float aSpeed;
  attribute float aAmp;
  attribute vec3 aColor;
  uniform float uTime;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vBright;

  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    // A slow sine per star, seeded phase and rate — no two twinkle together.
    float tw = 0.5 + 0.5 * sin(uTime * aSpeed + aPhase);
    float bright = (1.0 - aAmp) + aAmp * tw;
    vBright = bright;
    vColor = aColor;
    gl_PointSize = aSize * uPixelRatio * (300.0 / -mv.z) * (0.8 + 0.2 * bright);
    gl_Position = projectionMatrix * mv;
  }
`;

const TWINKLE_FRAGMENT = /* glsl */ `
  uniform float uGain;
  varying vec3 vColor;
  varying float vBright;

  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c) * 2.0;
    // Soft disc with a small hot core — reads as a point of light, not a dot.
    float alpha = smoothstep(1.0, 0.3, d) * 0.55 + smoothstep(0.35, 0.0, d) * 0.45;
    alpha *= vBright * uGain;
    if (alpha < 0.02) discard;
    gl_FragColor = vec4(vColor, alpha);
  }
`;

/** A seeded direction on the sphere, flattened like the 2D sky so the field
 *  reads as a heavens rather than a snow globe. */
function onSphere(rand: () => number, r: number): [number, number, number] {
  const theta = rand() * Math.PI * 2;
  const phi = Math.acos(2 * rand() - 1);
  return [
    Math.sin(phi) * Math.cos(theta) * r,
    Math.cos(phi) * r * 0.72,
    Math.sin(phi) * Math.sin(theta) * r,
  ];
}

/**
 * The star field: one `Points` draw for the whole sky. Positions, sizes,
 * twinkle phases and tints are seeded attributes; the only per-frame cost is
 * advancing a single time uniform.
 *
 * Tinted by stellar class rather than by the app's palette alone: mostly
 * white, with blue-white giants, a scatter of warm K-stars and a few deep red
 * dwarfs — the same ramp the box stars wear (`starSurface.ts`), so the sky's
 * stars and the rig's are the same kind of object.
 */
function TwinkleField() {
  const reduceMotion = useReduceMotion();
  const dpr = useThree((state) => state.gl.getPixelRatio());

  const { geometry, uniforms } = useMemo(() => {
    const rand = mulberry32(SKY_SEED);
    const positions = new Float32Array(FIELD_COUNT * 3);
    const sizes = new Float32Array(FIELD_COUNT);
    const phases = new Float32Array(FIELD_COUNT);
    const speeds = new Float32Array(FIELD_COUNT);
    const amps = new Float32Array(FIELD_COUNT);
    const colors = new Float32Array(FIELD_COUNT * 3);

    const white = new THREE.Color(GL.starlight);
    const blue = new THREE.Color("#c8d8ff");
    const warm = new THREE.Color("#ffd9a8");
    const red = new THREE.Color("#ff9a7a");
    const violet = new THREE.Color(GL.pulsar).lerp(white, 0.55);
    const green = new THREE.Color(GL.ion).lerp(white, 0.6);

    for (let i = 0; i < FIELD_COUNT; i += 1) {
      const [x, y, z] = onSphere(rand, FIELD_NEAR + rand() * (FIELD_FAR - FIELD_NEAR));
      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      // A few bright beacons over a majority of faint grains.
      const grade = rand();
      sizes[i] = grade > 0.93 ? 0.85 + rand() * 0.5 : 0.3 + rand() * 0.4;
      phases[i] = rand() * Math.PI * 2;
      speeds[i] = 0.4 + rand() * 1.6;
      amps[i] = grade > 0.93 ? 0.45 + rand() * 0.3 : 0.2 + rand() * 0.3;

      const roll = rand();
      const tint =
        roll > 0.94 ? red
          : roll > 0.84 ? warm
            : roll > 0.68 ? blue
              : roll > 0.62 ? violet
                : roll > 0.57 ? green
                  : white;
      colors[i * 3] = tint.r;
      colors[i * 3 + 1] = tint.g;
      colors[i * 3 + 2] = tint.b;
    }

    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    g.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
    g.setAttribute("aSpeed", new THREE.BufferAttribute(speeds, 1));
    g.setAttribute("aAmp", new THREE.BufferAttribute(amps, 1));
    g.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));

    return {
      geometry: g,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: 1 }, uGain: { value: 1 } },
    };
  }, []);

  useEffect(() => () => geometry.dispose(), [geometry]);
  uniforms.uPixelRatio.value = dpr;

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (!reduceMotion) uniforms.uTime.value += delta;
  });

  return (
    <points geometry={geometry} renderOrder={-2} frustumCulled={false}>
      <shaderMaterial
        vertexShader={TWINKLE_VERTEX}
        fragmentShader={TWINKLE_FRAGMENT}
        uniforms={uniforms}
        transparent
        depthWrite={false}
      />
    </points>
  );
}

/**
 * The dust band: thousands of the faintest points, concentrated in a belt
 * across the sky that lies along the home galaxy's plane. Individually
 * invisible; together, the glow of the disc seen from inside it. No twinkle
 * (a static uniform) — this layer is the one that must not shimmer, or the
 * band reads as noise rather than as light.
 */
function DustBand() {
  const dpr = useThree((state) => state.gl.getPixelRatio());

  const { geometry, uniforms } = useMemo(() => {
    const rand = mulberry32(SKY_SEED ^ 0x2d);
    const positions = new Float32Array(DUST_COUNT * 3);
    const sizes = new Float32Array(DUST_COUNT);
    const phases = new Float32Array(DUST_COUNT);
    const speeds = new Float32Array(DUST_COUNT);
    const amps = new Float32Array(DUST_COUNT);
    const colors = new Float32Array(DUST_COUNT * 3);
    const tint = new THREE.Color("#d8d4ea");
    const warm = new THREE.Color("#e8dcc4");

    // The band's plane: the home galaxy's own tilt and roll, so the haze
    // lies across the sky in front of the disc it belongs to — depth, for
    // free. Points are scattered on the shell, then pulled toward that plane.
    const normal = new THREE.Vector3(0, 1, 0)
      .applyEuler(new THREE.Euler(-0.95, 0, 0.32))
      .normalize();
    const p = new THREE.Vector3();
    for (let i = 0; i < DUST_COUNT; i += 1) {
      const [x, y, z] = onSphere(rand, FIELD_NEAR + 4 + rand() * (FIELD_FAR - FIELD_NEAR - 8));
      p.set(x, y / 0.72, z); // undo the flattening for the plane test
      // Squeeze toward the plane: subtract most of the out-of-plane component.
      const off = p.dot(normal);
      const squeeze = 0.12 + rand() * 0.22;
      p.addScaledVector(normal, -off * (1 - squeeze));
      p.normalize().multiplyScalar(FIELD_NEAR + 6 + rand() * 20);
      positions[i * 3] = p.x;
      positions[i * 3 + 1] = p.y * 0.72;
      positions[i * 3 + 2] = p.z;
      sizes[i] = 0.45 + rand() * 0.5;
      phases[i] = 0;
      speeds[i] = 0;
      amps[i] = 0;
      const c = rand() > 0.7 ? warm : tint;
      colors[i * 3] = c.r;
      colors[i * 3 + 1] = c.g;
      colors[i * 3 + 2] = c.b;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    g.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
    g.setAttribute("aSpeed", new THREE.BufferAttribute(speeds, 1));
    g.setAttribute("aAmp", new THREE.BufferAttribute(amps, 1));
    g.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));
    // Low gain: thousands of these at full strength would be a second star
    // field, and the point of this layer is to be seen only in aggregate.
    return {
      geometry: g,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: 1 }, uGain: { value: 0.32 } },
    };
  }, []);

  useEffect(() => () => geometry.dispose(), [geometry]);
  uniforms.uPixelRatio.value = dpr;

  return (
    <points geometry={geometry} renderOrder={-3} frustumCulled={false}>
      <shaderMaterial
        vertexShader={TWINKLE_VERTEX}
        fragmentShader={TWINKLE_FRAGMENT}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

// --- nebulae ----------------------------------------------------------------

interface NebulaPlacement {
  position: [number, number, number];
  scale: number;
  roll: number;
  drift: number;
  opacity: number;
  textureIndex: number;
}

/**
 * Cloud banks hung on the far shell. Deep, desaturated cousins of the palette
 * — violet from Pulsar's family, green from Ion's, a dusk tone, and now an
 * ember and a teal for range — kept at low opacity so they colour the darkness
 * without ever glowing. Nine of them, so the sky has weather in every
 * direction rather than three places.
 */
function NebulaField() {
  const reduceMotion = useReduceMotion();
  const meshes = useRef<THREE.Mesh[]>([]);

  const { textures, placements } = useMemo(() => {
    const made = [
      makeNebulaTexture(SKY_SEED ^ 0x1, "#5a4f8a", "#2a2447"), // violet
      makeNebulaTexture(SKY_SEED ^ 0x2, "#3f6b52", "#1c3026"), // green
      makeNebulaTexture(SKY_SEED ^ 0x3, "#5c4360", "#251a2e"), // dusk
      makeNebulaTexture(SKY_SEED ^ 0x4, "#7a4a3a", "#2e1c18"), // ember
      makeNebulaTexture(SKY_SEED ^ 0x5, "#3d5c6b", "#182a30"), // teal
    ];
    const rand = mulberry32(SKY_SEED ^ 0x9e);
    const placed: NebulaPlacement[] = Array.from({ length: 9 }, (_, i) => {
      const theta = rand() * Math.PI * 2;
      // Keep the banks off the poles — straight overhead they'd sit behind
      // nothing and straight below they'd never be seen.
      const phi = Math.PI / 2 + (rand() - 0.5) * 1.6;
      const r = NEBULA_NEAR + rand() * (NEBULA_FAR - NEBULA_NEAR);
      return {
        position: [
          Math.sin(phi) * Math.cos(theta) * r,
          Math.cos(phi) * r * 0.8,
          Math.sin(phi) * Math.sin(theta) * r,
        ] as [number, number, number],
        scale: 55 + rand() * 50,
        roll: rand() * Math.PI * 2,
        // Signed so neighbouring banks shear against each other.
        drift: (rand() - 0.5) * 0.012,
        // Kept firmly in the background: a bank that reads as a halo around
        // whichever star drifts in front of it has stopped being scenery.
        opacity: 0.34 + rand() * 0.22,
        textureIndex: i % made.length,
      };
    });
    return { textures: made, placements: placed };
  }, []);

  useEffect(() => () => textures.forEach((t) => t.dispose()), [textures]);

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (reduceMotion) return;
    placements.forEach((p, i) => {
      const mesh = meshes.current[i];
      if (mesh) mesh.rotation.z += delta * p.drift;
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
            scale={p.scale}
            renderOrder={-4}
          >
            <planeGeometry args={[1, 1]} />
            <meshBasicMaterial
              map={textures[p.textureIndex]!}
              transparent
              opacity={p.opacity}
              depthWrite={false}
            />
          </mesh>
        </Billboard>
      ))}
    </group>
  );
}
