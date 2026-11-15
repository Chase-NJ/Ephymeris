import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { mulberry32 } from "@/lib/prng";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { DistantGalaxies } from "./DistantGalaxies";
import { AT_INFINITY, makePointsMaterial, stellarTint } from "./farMaterials";
import { bakeFarSky, makeFarSkyTarget } from "./farSkyBake";
import { GALAXY_PLANE, HomeGalaxy } from "./HomeGalaxy";

/**
 * The sky at infinity — the part of the backdrop that does not drift
 * (`ARCHITECTURE.md#one-sky`).
 *
 * A painted dome (the galactic band and the nebulae, baked once), the home
 * galaxy, the distant galaxies and a field of faint fixed stars, all riding
 * with the camera's position. That makes it a true skybox: orbiting turns it
 * as any view turns, but nothing the camera or the drift does can move it, so
 * it is the still frame the drifting layers are seen to slide across. Its own
 * slow motions — the disc's turn, the twinkle — hold when `still`.
 *
 * Everything in it is drawn at the far plane (`AT_INFINITY`), so a box star or
 * a world always wins the depth test against it, however near the camera the
 * sky's geometry happens to sit.
 */
export function FarSky({ seed, still }: { seed: number; still: boolean }) {
  const camera = useThree((state) => state.camera);
  const anchor = useMemo(() => new CameraAnchor(camera), [camera]);

  return (
    <primitive object={anchor}>
      <NebulaDome seed={seed ^ 0x6e} />
      <DistantGalaxies seed={seed} still={still} />
      <HomeGalaxy seed={seed ^ 0x41} still={still} />
      <FixedStars seed={seed} still={still} />
    </primitive>
  );
}

/**
 * A group that sits wherever the camera is. Follows in `updateMatrixWorld`
 * rather than a `useFrame`, because that runs inside `render()` — after every
 * frame callback, the camera rig's included — so the sky never trails the
 * camera by a frame during a flight.
 */
class CameraAnchor extends THREE.Group {
  private readonly target: THREE.Camera;

  constructor(target: THREE.Camera) {
    super();
    this.target = target;
  }

  override updateMatrixWorld(force?: boolean): void {
    this.position.copy(this.target.position);
    super.updateMatrixWorld(force);
  }
}

// --- the dome -----------------------------------------------------------------

/** Inside the default camera's far plane (1000), though `AT_INFINITY` makes
 *  the radius immaterial to what it covers. */
const DOME_RADIUS = 500;

function NebulaDome({ seed }: { seed: number }) {
  const gl = useThree((state) => state.gl);
  const target = useMemo(() => makeFarSkyTarget(), []);
  const baked = useRef(false);
  useEffect(() => () => target.dispose(), [target]);

  // On the first frame rather than at mount: inside the frame loop the
  // renderer's state is its own, and the scene renders straight after with the
  // dome already painted.
  useFrame(() => {
    if (baked.current) return;
    bakeFarSky(gl, target, seed, GALAXY_PLANE);
    baked.current = true;
  });

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        uniforms: { uSky: { value: target.texture } },
        vertexShader: DOME_VERTEX,
        fragmentShader: DOME_FRAGMENT,
        side: THREE.BackSide,
        transparent: true,
        premultipliedAlpha: true,
        depthWrite: false,
      }),
    [target],
  );
  useEffect(() => () => material.dispose(), [material]);

  return (
    <mesh renderOrder={-10} frustumCulled={false} scale={DOME_RADIUS} material={material}>
      <sphereGeometry args={[1, 48, 24]} />
    </mesh>
  );
}

const DOME_VERTEX = /* glsl */ `
  varying vec3 vDir;
  void main() {
    vDir = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    ${AT_INFINITY}
  }
`;

const DOME_FRAGMENT = /* glsl */ `
  uniform samplerCube uSky;
  varying vec3 vDir;
  void main() {
    vec3 sky = texture(uSky, vDir).rgb;
    // Half a code value of interleaved-gradient dither: the dome is all slow
    // gradients near black, which an 8-bit swapchain would otherwise band.
    float dither = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
    sky = max(sky + (dither - 0.5) / 255.0, 0.0);
    gl_FragColor = vec4(sky, clamp(max(sky.r, max(sky.g, sky.b)), 0.0, 1.0));
  }
`;

// --- fixed stars ----------------------------------------------------------------

/** The far, faint star field — a shell around the camera. */
const FIXED_NEAR = 58;
const FIXED_FAR = 92;
const FIXED_COUNT = 1400;

const FIXED_VERTEX = /* glsl */ `
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
    ${AT_INFINITY}
  }
`;

/**
 * The stars too far away to drift: one `Points` draw, flattened like the 2D
 * sky so it reads as a heavens rather than a snow globe. Smaller and fainter
 * than the drifting mid-field, since they are the furthest stars there are.
 * Their twinkle holds when the sky is `still`.
 */
function FixedStars({ seed, still }: { seed: number; still: boolean }) {
  const dpr = useThree((state) => state.gl.getPixelRatio());

  const { geometry, uniforms, material } = useMemo(() => {
    const rand = mulberry32(seed);
    const positions = new Float32Array(FIXED_COUNT * 3);
    const sizes = new Float32Array(FIXED_COUNT);
    const phases = new Float32Array(FIXED_COUNT);
    const speeds = new Float32Array(FIXED_COUNT);
    const amps = new Float32Array(FIXED_COUNT);
    const colors = new Float32Array(FIXED_COUNT * 3);

    for (let i = 0; i < FIXED_COUNT; i += 1) {
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const r = FIXED_NEAR + rand() * (FIXED_FAR - FIXED_NEAR);
      positions[i * 3] = Math.sin(phi) * Math.cos(theta) * r;
      positions[i * 3 + 1] = Math.cos(phi) * r * 0.72;
      positions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r;

      // A few brighter points over a majority of faint grains.
      const grade = rand();
      sizes[i] = grade > 0.95 ? 0.6 + rand() * 0.4 : 0.22 + rand() * 0.3;
      phases[i] = rand() * Math.PI * 2;
      speeds[i] = 0.4 + rand() * 1.6;
      amps[i] = grade > 0.95 ? 0.45 + rand() * 0.3 : 0.2 + rand() * 0.3;

      const tint = stellarTint(rand);
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

    const u = { uTime: { value: 0 }, uPixelRatio: { value: 1 }, uGain: { value: 0.8 } };
    return { geometry: g, uniforms: u, material: makePointsMaterial(FIXED_VERTEX, u) };
  }, [seed]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);
  uniforms.uPixelRatio.value = dpr;

  useFrame((_state, raw) => {
    if (!still) uniforms.uTime.value += Math.min(raw, MAX_FRAME_SECONDS);
  });

  return (
    <points geometry={geometry} material={material} renderOrder={-6} frustumCulled={false} />
  );
}

