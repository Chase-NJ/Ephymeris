import * as THREE from "three";

/**
 * The stellar-surface material for Mission Control's constellation
 * (`starting-a-session.md` §6.2).
 *
 * A deliberate, bounded exception to §2.2's flat-matte rule: these are stars
 * standing in for animals, and a star that looks like a star carries real
 * information here — its **colour is its temperature, and its temperature is
 * that animal's pooled rolling accuracy**. Glancing at the constellation tells
 * you who is working. The exception stays inside this file and Mission
 * Control's 3D scene; nothing in the 2D chrome gains a gradient or a glow.
 *
 * Temperature follows the real stellar sequence, cool to hot:
 *
 * | Pooled accuracy | Reads as | Class |
 * |---|---|---|
 * | ≤ chance | deep red | M |
 * | ~0.6 | orange | K |
 * | ~0.7 | yellow | G, sun-like |
 * | ~0.85 | white | F/A |
 * | → 1.0 | blue-white | B |
 *
 * Chance is the floor rather than zero: below it an animal is not "colder",
 * it is doing something other than the task, and stretching the ramp down to
 * zero would spend half the visible range on a distinction nobody reads.
 */

/** Where the ramp starts — chance on a two-choice task. */
export const CHANCE = 0.5;

/** Anchors of the ramp, in linear-ish sRGB. Interpolated in between. */
const RAMP: Array<{ at: number; core: THREE.Color; edge: THREE.Color }> = [
  // M — deep red dwarf
  { at: 0.0, core: new THREE.Color("#ff6a3d"), edge: new THREE.Color("#8f2d1a") },
  // K — orange
  { at: 0.35, core: new THREE.Color("#ffa651"), edge: new THREE.Color("#a8521f") },
  // G — yellow, sun-like
  { at: 0.6, core: new THREE.Color("#ffd98a"), edge: new THREE.Color("#c98a2e") },
  // F/A — white
  { at: 0.82, core: new THREE.Color("#fdf6e8"), edge: new THREE.Color("#d8c9a8") },
  // B — blue-white
  { at: 1.0, core: new THREE.Color("#dbeaff"), edge: new THREE.Color("#7fa8e0") },
];

/**
 * Pooled accuracy → a 0–1 position on the ramp. `null` (nothing scored yet)
 * sits at the cool end: an animal that has not earned anything has not shown
 * you it is working, and showing it hot would be a claim the data can't make.
 */
export function temperatureFor(accuracy: number | null): number {
  if (accuracy === null) return 0;
  const above = (accuracy - CHANCE) / (1 - CHANCE);
  return Math.min(1, Math.max(0, above));
}

export function rampColors(t: number): { core: THREE.Color; edge: THREE.Color } {
  let lower = RAMP[0]!;
  let upper = RAMP[RAMP.length - 1]!;
  for (let i = 0; i < RAMP.length - 1; i += 1) {
    if (t >= RAMP[i]!.at && t <= RAMP[i + 1]!.at) {
      lower = RAMP[i]!;
      upper = RAMP[i + 1]!;
      break;
    }
  }
  const span = upper.at - lower.at;
  const k = span === 0 ? 0 : (t - lower.at) / span;
  return {
    core: lower.core.clone().lerp(upper.core, k),
    edge: lower.edge.clone().lerp(upper.edge, k),
  };
}

/**
 * Granulation: value-noise fBm over the surface position, plus limb darkening.
 *
 * Deliberately hash-based rather than a texture — a texture would need loading,
 * bundling, and a licence, and six animated spheres of this size cost nothing
 * either way. The noise scrolls slowly along one axis so the surface churns
 * without appearing to spin independently of the mesh.
 */
export const STAR_VERTEX = /* glsl */ `
  varying vec3 vPos;
  varying vec3 vNormal;
  void main() {
    vPos = position;
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const STAR_FRAGMENT = /* glsl */ `
  precision mediump float;

  uniform float uTime;
  uniform vec3 uCore;
  uniform vec3 uEdge;
  uniform float uActivity;   // 0 = still (unlit), 1 = fully churning
  varying vec3 vPos;
  varying vec3 vNormal;

  float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }

  float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);           // smoothstep the cell
    return mix(
      mix(mix(hash(i + vec3(0,0,0)), hash(i + vec3(1,0,0)), f.x),
          mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
          mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y),
      f.z);
  }

  float fbm(vec3 p) {
    float sum = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 4; i++) {
      sum += amp * noise(p);
      p *= 2.02;
      amp *= 0.5;
    }
    return sum;
  }

  void main() {
    // Two drifting noise fields: coarse convection cells over a finer churn.
    vec3 p = normalize(vPos) * 3.4;
    float drift = uTime * 0.05 * uActivity;
    float cells = fbm(p + vec3(0.0, drift, 0.0));
    float fine  = fbm(p * 2.7 - vec3(0.0, drift * 1.7, 0.0));
    float g = mix(cells, fine, 0.35);

    // Granule contrast: push the mid-range apart so cells read as cells rather
    // than as fog, then bias slightly bright so the star doesn't look sooty.
    g = clamp((g - 0.35) * 1.9 + 0.5, 0.0, 1.0);

    vec3 base = mix(uEdge, uCore, g);

    // Limb darkening — a real star dims toward its edge because you see less
    // deep, hot material there. It is what makes a flat disc read as a sphere.
    float facing = clamp(dot(normalize(vNormal), vec3(0.0, 0.0, 1.0)), 0.0, 1.0);
    float limb = 0.45 + 0.55 * pow(facing, 0.55);

    gl_FragColor = vec4(base * limb, 1.0);
  }
`;

/** A fresnel shell that reads as chromosphere, not as a bloom filter. */
export const CORONA_VERTEX = STAR_VERTEX;

export const CORONA_FRAGMENT = /* glsl */ `
  precision mediump float;
  uniform vec3 uCore;
  uniform float uStrength;
  varying vec3 vNormal;
  void main() {
    float facing = clamp(dot(normalize(vNormal), vec3(0.0, 0.0, 1.0)), 0.0, 1.0);
    // Brightest at the rim, gone at the centre: the shell only shows where it
    // is edge-on, which is the whole reason it doesn't look like a glow filter.
    float rim = pow(1.0 - facing, 2.6);
    gl_FragColor = vec4(uCore, rim * uStrength);
  }
`;
