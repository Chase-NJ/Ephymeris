import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";

/**
 * The cage-ship's hull — lit by its star, **without a light**.
 *
 * The belt used to carry a `pointLight` at the star's centre and the hull was a
 * `meshStandardMaterial`, which is the obvious way to get a day side and a
 * night side and was quietly the most expensive thing in the scene. three
 * compiles a material's program against the scene's light COUNTS
 * (`WebGLPrograms.getProgramCacheKey` — `numPointLights` is in the key of
 * every non-raw material, lit or not). One light per belt therefore meant:
 *
 *  - the count changed on entering the cohort browser, whenever a cohort gained
 *    or lost its cages, and on **every keystroke in the search box** (a dimmed
 *    world drops its fleet), and each change relinked the physical shader with
 *    one unrolled BRDF evaluation per light — a dozen of them, blocking a frame;
 *  - every *other* program in the scene was keyed on the same count, so a planet
 *    shader warmed ahead of time (`ProgramWarmth.tsx`) could never be hit.
 *
 * The scene now contains no lights at all, which makes every program key in the
 * app a constant. What the light was FOR is kept exactly: a Lambert term from
 * the direction of the belt's centre, so the terminator still crawls across a
 * hull as it orbits, over a Halo floor that keeps the night side legible
 * instead of vanishing. At annotation scale that is the whole of what the
 * physical model was contributing.
 *
 * Fenced the way `starSurface.ts` and `planetSurface.ts` are, and still nothing
 * here lands on Pulsar (`ARCHITECTURE.md#theme`).
 */

export const HULL_VERTEX = /* glsl */ `
  varying vec3 vNormalW;
  varying vec3 vWorld;
  void main() {
    // Ships are only ever scaled uniformly, so the model matrix's rotation
    // block is a valid normal transform without the inverse-transpose.
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

export const HULL_FRAGMENT = /* glsl */ `
  precision mediump float;

  uniform vec3  uStar;     // the belt's centre, world space — where the light is
  uniform vec3  uHull;     // Starlight
  uniform vec3  uFloor;    // Halo — the night side's own colour, never black
  uniform float uOpacity;
  varying vec3 vNormalW;
  varying vec3 vWorld;

  void main() {
    vec3 L = normalize(uStar - vWorld);
    float day = max(dot(normalize(vNormalW), L), 0.0);
    // A touch of wrap so the terminator is a gradient rather than a cut: at
    // a few pixels across, a hard edge reads as a rendering fault.
    float lit = smoothstep(0.0, 1.0, day * 0.85 + 0.15 * day * day);
    vec3 colour = uFloor * 0.85 + uHull * lit * 0.95;
    gl_FragColor = vec4(colour, uOpacity);
    #include <colorspace_fragment>
  }
`;

/** One hull material. The `uStar` uniform object is shared by every material
 *  in a belt, so the belt writes its position once and all of them see it. */
export function createHullMaterial(
  star: { value: THREE.Vector3 },
  opacity: number,
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: HULL_VERTEX,
    fragmentShader: HULL_FRAGMENT,
    uniforms: {
      uStar: star,
      uHull: { value: new THREE.Color(GL.starlight) },
      uFloor: { value: new THREE.Color(GL.halo) },
      uOpacity: { value: opacity },
    },
    transparent: true,
  });
}

/**
 * The ship's parts, built ONCE at unit scale and shared by every craft.
 *
 * Each ship used to construct its own twelve geometries sized off its star's
 * radius; a library of a dozen cohorts is about a hundred ships, so opening the
 * cohort browser built and uploaded over a thousand buffers in one commit. The
 * proportions never varied — only the scale did — so the craft is modelled at
 * `starRadius = 1` and the instance is scaled instead.
 *
 * Shared objects are passed as props, and the meshes that take them carry
 * `dispose={null}`: r3f otherwise disposes a mesh's `geometry` and `material`
 * when it unmounts, which for a shared one frees the buffers under every other
 * ship still flying.
 */
export const SHIP_GEOMETRY = {
  fuselage: new THREE.CapsuleGeometry(0.055, 0.2, 4, 10),
  canopy: new THREE.SphereGeometry(0.032, 10, 10),
  fin: new THREE.BoxGeometry(0.11, 0.012, 0.09),
  nozzle: new THREE.CylinderGeometry(0.05, 0.032, 0.05, 10),
  throat: new THREE.SphereGeometry(0.028, 8, 8),
  plume: new THREE.ConeGeometry(0.022, 0.16, 8, 1, true),
  beacon: new THREE.SphereGeometry(0.042, 8, 8),
  bloom: new THREE.SphereGeometry(0.055, 8, 8),
  lamp: new THREE.SphereGeometry(0.034, 8, 8),
} as const;
