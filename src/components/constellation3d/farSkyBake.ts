import * as THREE from "three";

import { mulberry32 } from "@/lib/prng";

/**
 * The far sky's painted dome, baked once into a cube map
 * (`ARCHITECTURE.md#one-sky`).
 *
 * Domain-warped fbm is far too much work to run per pixel per frame on the
 * lab's integrated GPUs, and the far sky never changes, so it is rendered once
 * — six faces of a cube camera on the first frame — and afterwards the dome
 * costs one cube lookup per pixel. The program links once per app run: the
 * backdrop is permanent in `SharedCanvas`, so nothing ever bakes it again.
 *
 * What it paints, in direction space:
 *
 * - **A band** — the faint glow of a galactic plane across the sky, clumped
 *   and cut by dark dust rifts, lying in the home galaxy's own plane so the
 *   haze sits where the disc does.
 * - **Nebulae** — warped cloud banks covering about a quarter of the sky, in
 *   the deep desaturated cousins of the palette the painted nebula sprites
 *   used to wear, so the sky's colours carried over.
 *
 * Kept dim on purpose: it colours the darkness and never glows
 * (`ARCHITECTURE.md#theme`).
 *
 * **The noise lattice is seeded on the CPU**, not hashed in GLSL: a `sin` hash
 * is not the same function on ANGLE/D3D as on Metal, and the backdrop's
 * contract is the same sky on every machine. A 32³ texture of `mulberry32`
 * draws, sampled with a smoothstepped trilinear fetch, is.
 */

/** Cube face edge, texels. The dome is soft — clouds and haze, no points —
 *  so a texel can span several screen pixels; at half float this is ~12 MB. */
export const FAR_SKY_FACE = 512;

const LATTICE = 32;

export function makeFarSkyTarget(): THREE.WebGLCubeRenderTarget {
  return new THREE.WebGLCubeRenderTarget(FAR_SKY_FACE, {
    type: THREE.HalfFloatType,
    generateMipmaps: false,
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
  });
}

/** Paint the far sky into `target`. Everything the bake builds is disposed
 *  before it returns; only the target's texture survives. */
export function bakeFarSky(
  gl: THREE.WebGLRenderer,
  target: THREE.WebGLCubeRenderTarget,
  seed: number,
  bandNormal: THREE.Vector3,
): void {
  const lattice = makeLattice(seed);
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uNoise: { value: lattice },
      uBandNormal: { value: bandNormal.clone().normalize() },
      uBandCore: { value: display("#e8dcc4") },
      uBandEdge: { value: display("#5a4f8a") },
      uHue: { value: NEBULA_HUES.map(display) },
    },
    vertexShader: BAKE_VERTEX,
    fragmentShader: BAKE_FRAGMENT,
    side: THREE.BackSide,
    blending: THREE.NoBlending,
    depthTest: false,
    depthWrite: false,
  });
  const geometry = new THREE.SphereGeometry(10, 64, 32);
  const scene = new THREE.Scene();
  scene.add(new THREE.Mesh(geometry, material));

  const camera = new THREE.CubeCamera(0.1, 100, target);
  camera.update(gl, scene);

  geometry.dispose();
  material.dispose();
  lattice.dispose();
}

/** The nebula hues — violet, green, dusk, ember, teal — in the order the hue
 *  noise walks them, so neighbouring banks shade into related colours. */
const NEBULA_HUES = ["#3d5c6b", "#3f6b52", "#5a4f8a", "#5c4360", "#7a4a3a"];

/** A hex colour as the raw display value the dome writes. The dome bypasses
 *  colour management (its output is already display-referred), so the hex is
 *  what lands on screen. */
function display(hex: string): THREE.Vector3 {
  const c = new THREE.Color(hex);
  const out = { r: 0, g: 0, b: 0 };
  c.getRGB(out, THREE.SRGBColorSpace);
  return new THREE.Vector3(out.r, out.g, out.b);
}

function makeLattice(seed: number): THREE.Data3DTexture {
  const rand = mulberry32(seed);
  const data = new Uint8Array(LATTICE ** 3);
  for (let i = 0; i < data.length; i += 1) data[i] = Math.floor(rand() * 256);
  const texture = new THREE.Data3DTexture(data, LATTICE, LATTICE, LATTICE);
  texture.format = THREE.RedFormat;
  texture.type = THREE.UnsignedByteType;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.wrapR = THREE.RepeatWrapping;
  texture.unpackAlignment = 1;
  texture.needsUpdate = true;
  return texture;
}

const BAKE_VERTEX = /* glsl */ `
  varying vec3 vDir;
  void main() {
    vDir = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const BAKE_FRAGMENT = /* glsl */ `
  precision highp sampler3D;
  uniform sampler3D uNoise;
  uniform vec3 uBandNormal;
  uniform vec3 uBandCore;
  uniform vec3 uBandEdge;
  uniform vec3 uHue[5];
  varying vec3 vDir;

  // Rotate each octave so the lattice's axes and its 32-cell period never
  // line up into a visible grain.
  const mat3 OCTAVE = mat3(0.00, 0.80, 0.60, -0.80, 0.36, -0.48, -0.60, -0.48, 0.64);

  // Value noise from the seeded lattice: a smoothstepped trilinear fetch.
  float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return texture(uNoise, (i + f + 0.5) / ${LATTICE.toFixed(1)}).r;
  }

  float fbm(vec3 p) {
    float sum = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 5; i++) {
      sum += amp * noise(p);
      p = OCTAVE * p * 2.02;
      amp *= 0.5;
    }
    return sum / 0.96875;
  }

  vec3 hueAt(float h) {
    h = clamp(h, 0.0, 1.0) * 4.0;
    int i = int(floor(h));
    float t = smoothstep(0.0, 1.0, fract(h));
    return mix(uHue[min(i, 4)], uHue[min(i + 1, 4)], t);
  }

  void main() {
    vec3 d = normalize(vDir);

    // The band: a Gaussian about the plane, clumped, with dust rifts cut
    // along its spine.
    float b = dot(d, uBandNormal);
    float profile = exp(-b * b / (2.0 * 0.16 * 0.16));
    float spine = exp(-b * b / (2.0 * 0.06 * 0.06));
    vec3 warp = vec3(fbm(d * 3.0 + 1.7), fbm(d * 3.0 + 8.3), fbm(d * 3.0 + 4.1));
    float clumps = fbm(d * 5.0 + warp * 0.8);
    float rift = smoothstep(0.5, 0.64, fbm(d * 7.0 + warp * 1.5))
      * exp(-b * b / (2.0 * 0.08 * 0.08));
    float band = profile * (0.2 + clumps * clumps * 1.6) * (1.0 - 0.85 * rift);
    vec3 color = mix(uBandEdge, uBandCore, spine * 0.8) * band * 0.16;

    // Nebulae: warped fbm, thresholded into banks, threaded with filaments.
    vec3 q = d * 2.2;
    vec3 w = vec3(fbm(q + 3.1), fbm(q + 11.7), fbm(q + 6.9));
    float n = fbm(q + w * 1.8);
    float cloud = smoothstep(0.5, 0.78, n);
    float filament = fbm(d * 10.0 + w * 2.0);
    cloud *= 0.45 + filament * filament * 1.4;
    vec3 hue = hueAt(fbm(d * 1.3 + 21.0) * 2.2 - 0.6);
    color += hue * cloud * 0.32;

    // Premultiplied: the dome composites over the page's Void, so darkness
    // must stay transparent rather than paint black over the 2D sky.
    float alpha = clamp(max(color.r, max(color.g, color.b)), 0.0, 1.0);
    gl_FragColor = vec4(color, alpha);
  }
`;
