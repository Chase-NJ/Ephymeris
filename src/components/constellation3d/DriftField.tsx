import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { advanceDrift, DRIFT_CLEARANCE, DRIFT_SPEED } from "@/lib/constellations/skyDrift";
import { mulberry32 } from "@/lib/prng";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { makePointsMaterial, stellarTint } from "./farMaterials";

/**
 * A layer of stars we are drifting past (`ARCHITECTURE.md#one-sky`).
 *
 * The stars fill a box centred on the origin and slide through it along
 * `DRIFT_DIR`; the vertex shader wraps each one back into the box, so a fixed
 * buffer streams forever and the only per-frame cost is one offset uniform.
 * Three fades keep the stream honest:
 *
 * - **The data bubble.** A star fades out before it comes within
 *   `DRIFT_CLEARANCE` of the origin, so none ever passes between the camera
 *   and a box star or a world.
 * - **The camera.** Fades out near the eye, and the point size is capped, so
 *   a camera orbiting at full distance never has a star in its face.
 * - **The wrap.** Fades out approaching the box's faces, so a star that wraps
 *   leaves invisibly and arrives invisibly on the other side.
 *
 * Every layer moves at the same speed; nearer layers cross the frame faster
 * only because they are nearer. That difference is the parallax that reads as
 * travel. Held, not hidden, when `still`.
 */
export function DriftField({
  seed,
  count,
  size,
  sizeRange,
  gain,
  twinkle,
  tint,
  renderOrder,
  still,
}: {
  seed: number;
  count: number;
  /** Edge of the wrapping box, world units. */
  size: number;
  /** Point size, smallest and largest, in the same units as `FarSky`'s stars. */
  sizeRange: [number, number];
  gain: number;
  /** Twinkle depth, 0 (steady) to 1. */
  twinkle: number;
  /** A fixed tint, or stellar-class tints when omitted. */
  tint?: string;
  renderOrder: number;
  still: boolean;
}) {
  const dpr = useThree((state) => state.gl.getPixelRatio());
  const offset = useRef([0, 0, 0]);

  const { geometry, uniforms, material } = useMemo(() => {
    const rand = mulberry32(seed);
    const positions = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const phases = new Float32Array(count);
    const speeds = new Float32Array(count);
    const amps = new Float32Array(count);
    const colors = new Float32Array(count * 3);
    const fixed = tint ? new THREE.Color(tint) : null;

    for (let i = 0; i < count; i += 1) {
      positions[i * 3] = rand() * size;
      positions[i * 3 + 1] = rand() * size;
      positions[i * 3 + 2] = rand() * size;
      // A few brighter points over a majority of faint ones.
      const grade = rand();
      const [lo, hi] = sizeRange;
      sizes[i] = grade > 0.93 ? hi + rand() * (hi - lo) * 0.6 : lo + rand() * (hi - lo);
      phases[i] = rand() * Math.PI * 2;
      speeds[i] = 0.4 + rand() * 1.6;
      amps[i] = twinkle * (0.4 + rand() * 0.6);
      const c = fixed ?? stellarTint(rand);
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

    const u = {
      uOffset: { value: new THREE.Vector3() },
      uSize: { value: size },
      uClearance: { value: DRIFT_CLEARANCE },
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uGain: { value: gain },
    };
    return { geometry: g, uniforms: u, material: makePointsMaterial(DRIFT_VERTEX, u) };
  }, [seed, count, size, sizeRange, gain, twinkle, tint]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);
  uniforms.uPixelRatio.value = dpr;

  useFrame((_state, raw) => {
    if (still) return;
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    advanceDrift(offset.current, delta * DRIFT_SPEED, size);
    uniforms.uOffset.value.fromArray(offset.current);
    uniforms.uTime.value += delta;
  });

  return (
    <points
      geometry={geometry}
      material={material}
      renderOrder={renderOrder}
      frustumCulled={false}
    />
  );
}

const DRIFT_VERTEX = /* glsl */ `
  attribute float aSize;
  attribute float aPhase;
  attribute float aSpeed;
  attribute float aAmp;
  attribute vec3 aColor;
  uniform vec3 uOffset;
  uniform float uSize;
  uniform float uClearance;
  uniform float uTime;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vBright;

  void main() {
    float halfSize = uSize * 0.5;
    vec3 p = mod(position + uOffset, uSize) - halfSize;

    // Fade at the wrap, so no star pops in or out at the box's faces.
    vec3 ap = abs(p);
    float edge = max(ap.x, max(ap.y, ap.z)) / halfSize;
    float alpha = 1.0 - smoothstep(0.85, 1.0, edge);
    // Fade before the data bubble.
    alpha *= smoothstep(uClearance, uClearance + 15.0, length(p));

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    float dist = -mv.z;
    // Fade near the eye (and behind it).
    alpha *= smoothstep(25.0, 40.0, dist);

    float tw = 0.5 + 0.5 * sin(uTime * aSpeed + aPhase);
    vBright = alpha * ((1.0 - aAmp) + aAmp * tw);
    vColor = aColor;

    float px = aSize * uPixelRatio * (300.0 / max(dist, 1.0));
    gl_PointSize = vBright < 0.01 ? 0.0 : min(px, 5.0 * uPixelRatio);
    gl_Position = projectionMatrix * mv;
  }
`;
