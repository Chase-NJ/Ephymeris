import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";

/**
 * Shared pieces of the backdrop's far sky (`FarSky.tsx`).
 *
 * The far sky rides with the camera, so its geometry can sit nearer the camera
 * than a box star on the far side of the asterism. Depth would then let a
 * distant galaxy paint over a star an operator is reading. So everything at
 * infinity is drawn **at the far plane** — `gl_Position.z = gl_Position.w`
 * — where any real geometry wins the depth test against it. That is
 * `AT_INFINITY`, appended to the end of every far-sky vertex shader.
 */
export const AT_INFINITY = /* glsl */ `
  gl_Position.z = gl_Position.w;
`;

const FAR_SPRITE_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    ${AT_INFINITY}
  }
`;

/* What `meshBasicMaterial` with a map computes, tone mapping and output
 * encoding included, so a sprite looks the same as it did before it moved to
 * infinity. */
const FAR_SPRITE_FRAGMENT = /* glsl */ `
  uniform sampler2D map;
  uniform float opacity;
  varying vec2 vUv;
  void main() {
    vec4 texel = texture2D(map, vUv);
    gl_FragColor = vec4(texel.rgb, texel.a * opacity);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

/** A textured quad at infinity: a distant galaxy, the home galaxy's haze. */
export function makeFarSpriteMaterial(
  map: THREE.Texture,
  opacity: number,
  { additive = false, doubleSide = false }: { additive?: boolean; doubleSide?: boolean } = {},
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: { map: { value: map }, opacity: { value: opacity } },
    vertexShader: FAR_SPRITE_VERTEX,
    fragmentShader: FAR_SPRITE_FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    side: doubleSide ? THREE.DoubleSide : THREE.FrontSide,
  });
}

const WHITE = new THREE.Color(GL.starlight);
const BLUE = new THREE.Color("#c8d8ff");
const WARM = new THREE.Color("#ffd9a8");
const RED = new THREE.Color("#ff9a7a");
const VIOLET = new THREE.Color(GL.pulsar).lerp(WHITE, 0.55);
const GREEN = new THREE.Color(GL.ion).lerp(WHITE, 0.6);

/**
 * A backdrop star's tint, by stellar class rather than by the app's palette
 * alone: mostly white, with blue-white giants, a scatter of warm K-stars and a
 * few deep red dwarfs — the same ramp the box stars wear (`starSurface.ts`), so
 * the sky's stars and the rig's are the same kind of object. One draw from
 * `rand`, so a layer's stream stays in step whatever the roll.
 */
export function stellarTint(rand: () => number): THREE.Color {
  const roll = rand();
  return roll > 0.94 ? RED
    : roll > 0.84 ? WARM
      : roll > 0.68 ? BLUE
        : roll > 0.62 ? VIOLET
          : roll > 0.57 ? GREEN
            : WHITE;
}

/**
 * A backdrop `Points` material, built as an object rather than a JSX
 * `<shaderMaterial uniforms={…}>`. r3f copies each entry of a `uniforms` prop
 * into the material (`{ ...uniform }`), so a frame callback that reassigns
 * `uniforms.uTime.value` on its own object never reaches the GPU — the
 * twinkle silently froze that way. Handed over whole via `material={…}`, the
 * material holds the caller's uniforms and every per-frame write lands.
 */
export function makePointsMaterial(
  vertexShader: string,
  uniforms: Record<string, THREE.IUniform>,
): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms,
    vertexShader,
    fragmentShader: POINT_FRAGMENT,
    transparent: true,
    depthWrite: false,
  });
}

/**
 * The fragment every backdrop point shares: a soft disc with a small hot core,
 * so it reads as a point of light rather than a dot.
 */
export const POINT_FRAGMENT = /* glsl */ `
  uniform float uGain;
  varying vec3 vColor;
  varying float vBright;

  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c) * 2.0;
    float alpha = smoothstep(1.0, 0.3, d) * 0.55 + smoothstep(0.35, 0.0, d) * 0.45;
    alpha *= vBright * uGain;
    if (alpha < 0.02) discard;
    gl_FragColor = vec4(vColor, alpha);
  }
`;
