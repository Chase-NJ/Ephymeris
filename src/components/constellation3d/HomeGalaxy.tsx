import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { makeSpiralTexture } from "./skyTextures";

/**
 * The galaxy we orbit — a spiral disc of a few thousand points, inclined
 * toward us and close enough to fill a third of the default frame.
 *
 * It is the thing the rest of the sky is arranged around and the one piece of
 * scenery with a shape the eye can hold: a bright bulge low in the frame, two
 * arms winding out of it with star-forming knots along them, dust lanes as the
 * gaps between. Points rather than a painted sprite because a disc this near
 * has parallax — the near arm slides against the far one as the camera orbits
 * — and a sprite would turn with the camera and give that away.
 *
 * Not a band we are *inside*. That was the first cut, and a disc through the
 * origin sweeps its near arm through the camera's data volume, which nothing
 * in the sky may enter. A great neighbour, seen from just outside its rim, is
 * the reading "orbiting a galaxy" can honestly have.
 *
 * It turns. Imperceptibly, at a rate that moves the bulge a few degrees over
 * an hour's session, which is the difference between a picture of a galaxy
 * and being somewhere. Still under reduced motion.
 *
 * One `Points` draw; the only per-frame cost is one rotation and a time
 * uniform for the faint shimmer of the arm knots.
 */
export function HomeGalaxy({ seed }: { seed: number }) {
  const reduceMotion = useReduceMotion();
  const dpr = useThree((state) => state.gl.getPixelRatio());
  const disc = useRef<THREE.Points>(null);

  const { geometry, uniforms } = useMemo(() => {
    const rand = mulberry32(seed);
    const positions = new Float32Array(GALAXY_COUNT * 3);
    const sizes = new Float32Array(GALAXY_COUNT);
    const colors = new Float32Array(GALAXY_COUNT * 3);
    const phases = new Float32Array(GALAXY_COUNT);

    const core = new THREE.Color("#fff1d6");
    const arm = new THREE.Color("#cfd8ff");
    const hii = new THREE.Color(GL.pulsar).lerp(new THREE.Color("#ff9ad6"), 0.4);
    const dust = new THREE.Color("#6f6a8a");

    for (let i = 0; i < GALAXY_COUNT; i += 1) {
      // Radius biased toward the centre; a bulge is most of the light.
      const t = rand();
      const r = Math.pow(t, 0.55) * GALAXY_RADIUS;
      // Two arms: an angle that winds with radius, plus scatter that grows
      // outward so the arms blur into the disc rather than ending in lines.
      const armIndex = rand() < 0.5 ? 0 : 1;
      const wind = (r / GALAXY_RADIUS) * ARM_WIND;
      const scatter = (rand() - 0.5) * (0.35 + (r / GALAXY_RADIUS) * 1.4);
      const theta = armIndex * Math.PI + wind + scatter;
      // Thickness: a thin disc, thicker at the bulge.
      const thick = (rand() - 0.5) * 2 * (2.5 + 12 * Math.exp(-r / 14));

      positions[i * 3] = Math.cos(theta) * r;
      positions[i * 3 + 1] = thick;
      positions[i * 3 + 2] = Math.sin(theta) * r;

      const inBulge = r < GALAXY_RADIUS * 0.16;
      const onArm = Math.abs(scatter) < 0.22;
      const roll = rand();
      let tint: THREE.Color;
      if (inBulge) tint = core;
      else if (onArm && roll > 0.86) tint = hii; // star-forming knots along the arms
      else if (onArm) tint = arm;
      else tint = roll > 0.5 ? dust : arm;
      colors[i * 3] = tint.r;
      colors[i * 3 + 1] = tint.g;
      colors[i * 3 + 2] = tint.b;

      sizes[i] = inBulge ? 1.6 + rand() * 1.6 : onArm ? 0.9 + rand() * 1.1 : 0.55 + rand() * 0.6;
      phases[i] = rand() * Math.PI * 2;
    }

    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    g.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));
    g.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
    return {
      geometry: g,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: 1 } },
    };
  }, [seed]);

  useEffect(() => () => geometry.dispose(), [geometry]);
  uniforms.uPixelRatio.value = dpr;

  /* The disc's body: one painted spiral haze lying in the disc plane under
   * the points. Four thousand sprites are a scatter; the same four thousand
   * over a soft glow are a galaxy. It is the same painter the distant
   * galaxies use, seeded from this one, so near and far agree on what a
   * spiral looks like. One quad. */
  const haze = useMemo(() => makeSpiralTexture(seed ^ 0x99, "#6f66b8", 2, 0.24), [seed]);
  useEffect(() => () => haze.dispose(), [haze]);
  const glow = useRef<THREE.Mesh>(null);

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (reduceMotion) return;
    uniforms.uTime.value += delta;
    if (disc.current) disc.current.rotation.y += delta * GALAXY_SPIN;
    // The haze turns with the points, or the arms would slide off their glow.
    if (glow.current) glow.current.rotation.z -= delta * GALAXY_SPIN;
  });

  return (
    // Deep, below the default eye-line and inclined toward us: the bulge sits
    // low in the default frame with the arms sweeping up and across it. Not a
    // band we are inside — a disc we are inside would sweep its near arm
    // through the camera's data volume, which nothing in the sky may enter
    // (`GALAXY_DISTANCE`). A great neighbour, close enough to fill a third of
    // the sky, is the reading "orbiting a galaxy" can honestly have.
    <group rotation={[GALAXY_TILT, 0, GALAXY_ROLL]} position={[0, -46, -GALAXY_DISTANCE]}>
      {/* Lies in the disc plane (the points' x-z), not billboarded. */}
      {/* Faint on purpose — an underglow the points sit on, not a picture
          the points decorate. At a third of this it read as a grey smudge
          with a scatter across it. */}
      <mesh ref={glow} rotation={[-Math.PI / 2, 0, 0]} scale={GALAXY_RADIUS * 1.9} renderOrder={-4}>
        <planeGeometry args={[1, 1]} />
        <meshBasicMaterial
          map={haze}
          transparent
          opacity={0.13}
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      <points
        ref={disc}
        geometry={geometry}
        renderOrder={-3}
        frustumCulled={false}
      >
        <shaderMaterial
          vertexShader={GALAXY_VERTEX}
          fragmentShader={GALAXY_FRAGMENT}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
    </group>
  );
}

const GALAXY_VERTEX = /* glsl */ `
  attribute float aSize;
  attribute vec3 aColor;
  attribute float aPhase;
  uniform float uTime;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vBright;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    // A very slow shimmer, so the arms breathe rather than sit.
    float tw = 0.85 + 0.15 * sin(uTime * 0.35 + aPhase);
    vBright = tw;
    vColor = aColor;
    gl_PointSize = aSize * uPixelRatio * (420.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const GALAXY_FRAGMENT = /* glsl */ `
  varying vec3 vColor;
  varying float vBright;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c) * 2.0;
    float alpha = smoothstep(1.0, 0.2, d) * 0.7 * vBright;
    if (alpha < 0.02) discard;
    gl_FragColor = vec4(vColor, alpha);
  }
`;

/** Points in the disc. One draw, whatever the count; the cost is the fill of
 *  a few thousand small sprites, which an integrated GPU does not notice. */
const GALAXY_COUNT = 4200;
/** World units. */
const GALAXY_RADIUS = 150;
/** How far the disc's centre sits from the origin along the default view.
 *  With the radius above, the nearest point of the disc is 65 units out —
 *  well past `maxDistance` (40), so the camera can never reach the near arm
 *  and no piece of it can occlude a box or a world. */
const GALAXY_DISTANCE = 215;
/** Radians the arms wind over the radius. */
const ARM_WIND = 2.6;
/** Radians per second. About one degree every eight seconds — invisible in a
 *  glance, unmistakable across a session. */
const GALAXY_SPIN = 0.0022;
/** Inclined toward the camera, rolled a little, so it is a spiral and not an
 *  ellipse — and not a line. */
const GALAXY_TILT = -0.95;
const GALAXY_ROLL = 0.32;
