import { Billboard } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The deep-sky backdrop behind both 3D constellation browsers: a twinkling
 * star field, slow nebula banks, and the occasional supernova.
 *
 * Everything here is scenery, and scenery in this app obeys two rules. It is
 * **deterministic** — every position, hue, phase and flare is seeded through
 * `mulberry32`, so the sky is the same sky on every mount and every machine
 * (the same contract the 2D `Starfield` and the cohort icons honour). And it
 * is **behind the data**: the field lives on a shell far outside the camera's
 * `maxDistance`, nebulae sit further still, and everything renders at low
 * opacity with `depthWrite` off, so no strobe of scenery ever occludes or
 * competes with a star an operator is reading.
 *
 * Under reduced motion the whole backdrop holds still: the twinkle freezes at
 * its seeded phase, nebulae stop drifting, and supernovae simply never happen
 * — the field stays, the theatre goes.
 */

/** Backdrop stars live on this shell — outside `maxDistance` (40), so the
 *  camera can never dolly through the sky. */
const FIELD_NEAR = 58;
const FIELD_FAR = 92;
const FIELD_COUNT = 720;

/** Nebulae sit behind the stars, so points twinkle *in front* of the clouds. */
const NEBULA_NEAR = 100;
const NEBULA_FAR = 135;

/** One backdrop seed — change it and a different (equally permanent) sky. */
const SKY_SEED = 0xa57e21;

export function SceneBackdrop() {
  return (
    <group>
      <NebulaField />
      <TwinkleField />
      <Supernovae />
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
  varying vec3 vColor;
  varying float vBright;

  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c) * 2.0;
    // Soft disc with a small hot core — reads as a point of light, not a dot.
    float alpha = smoothstep(1.0, 0.3, d) * 0.55 + smoothstep(0.35, 0.0, d) * 0.45;
    alpha *= vBright;
    if (alpha < 0.02) discard;
    gl_FragColor = vec4(vColor, alpha);
  }
`;

/**
 * The star field: one `Points` draw for the whole sky. Positions, sizes,
 * twinkle phases and tints are seeded attributes; the only per-frame cost is
 * advancing a single time uniform.
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

    // The same palette family as everything else: mostly Starlight, with a
    // scattering of Pulsar-violet and Ion-green tints kept close to white.
    const starlight = new THREE.Color(GL.starlight);
    const violet = new THREE.Color(GL.pulsar).lerp(starlight, 0.55);
    const green = new THREE.Color(GL.ion).lerp(starlight, 0.6);

    for (let i = 0; i < FIELD_COUNT; i += 1) {
      // Uniform direction on the sphere, flattened like the 2D sky so the
      // field reads as a heavens rather than a snow globe.
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const r = FIELD_NEAR + rand() * (FIELD_FAR - FIELD_NEAR);
      positions[i * 3] = Math.sin(phi) * Math.cos(theta) * r;
      positions[i * 3 + 1] = Math.cos(phi) * r * 0.72;
      positions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r;

      // A few bright beacons over a majority of faint grains.
      const grade = rand();
      sizes[i] = grade > 0.93 ? 0.85 + rand() * 0.5 : 0.35 + rand() * 0.4;
      phases[i] = rand() * Math.PI * 2;
      speeds[i] = 0.4 + rand() * 1.6;
      // How deeply this star twinkles; the bright ones flicker hardest.
      amps[i] = grade > 0.93 ? 0.45 + rand() * 0.3 : 0.2 + rand() * 0.3;

      const tintRoll = rand();
      const tint = tintRoll > 0.85 ? violet : tintRoll > 0.75 ? green : starlight;
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
      uniforms: {
        uTime: { value: 0 },
        uPixelRatio: { value: 1 },
      },
    };
  }, []);

  useEffect(() => () => geometry.dispose(), [geometry]);

  uniforms.uPixelRatio.value = dpr;

  useFrame((_state, delta) => {
    // Frozen under reduced motion: each star holds its seeded brightness.
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

// --- nebulae ----------------------------------------------------------------

/**
 * A soft cloud texture, painted once per hue pair on an offscreen canvas —
 * layered translucent blobs, then an overall radial fade so the quad has no
 * visible edge. Procedural because the app ships no image assets, and seeded
 * so the same clouds hang in the same sky forever.
 */
function makeNebulaTexture(
  seed: number,
  core: string,
  edge: string,
): THREE.CanvasTexture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const rand = mulberry32(seed);

  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < 26; i += 1) {
    // Blobs cluster toward the centre and shrink toward the rim, which is
    // what makes it read as one cloud rather than confetti.
    const angle = rand() * Math.PI * 2;
    const spread = rand() ** 1.6 * size * 0.34;
    const x = size / 2 + Math.cos(angle) * spread;
    const y = size / 2 + Math.sin(angle) * spread * 0.7;
    const radius = size * (0.08 + rand() * 0.22) * (1 - spread / size);
    const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
    const hue = rand() > 0.4 ? core : edge;
    gradient.addColorStop(0, `${hue}1a`);
    gradient.addColorStop(0.55, `${hue}0d`);
    gradient.addColorStop(1, `${hue}00`);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  }

  // Fade the whole cloud out toward the quad's edge.
  ctx.globalCompositeOperation = "destination-in";
  const fade = ctx.createRadialGradient(
    size / 2,
    size / 2,
    size * 0.1,
    size / 2,
    size / 2,
    size * 0.5,
  );
  fade.addColorStop(0, "rgba(255,255,255,1)");
  fade.addColorStop(0.7, "rgba(255,255,255,0.6)");
  fade.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = fade;
  ctx.fillRect(0, 0, size, size);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

interface NebulaPlacement {
  position: [number, number, number];
  scale: number;
  roll: number;
  drift: number;
  opacity: number;
  textureIndex: number;
}

/**
 * Half a dozen cloud banks hung on the far shell. Deep, desaturated cousins of
 * the palette — violet from Pulsar's family, green from Ion's, plus a dusk tone
 * — kept at low opacity so they colour the darkness without ever glowing.
 */
function NebulaField() {
  const reduceMotion = useReduceMotion();
  const meshes = useRef<THREE.Mesh[]>([]);

  const { textures, placements } = useMemo(() => {
    const made = [
      makeNebulaTexture(SKY_SEED ^ 0x1, "#5a4f8a", "#2a2447"), // violet
      makeNebulaTexture(SKY_SEED ^ 0x2, "#3f6b52", "#1c3026"), // green
      makeNebulaTexture(SKY_SEED ^ 0x3, "#5c4360", "#251a2e"), // dusk
    ];
    const rand = mulberry32(SKY_SEED ^ 0x9e);
    const placed: NebulaPlacement[] = Array.from({ length: 7 }, (_, i) => {
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
        scale: 55 + rand() * 45,
        roll: rand() * Math.PI * 2,
        // Signed so neighbouring banks shear against each other.
        drift: (rand() - 0.5) * 0.012,
        // Kept firmly in the background: a bank that reads as a halo around
        // whichever star drifts in front of it has stopped being scenery.
        opacity: 0.34 + rand() * 0.2,
        textureIndex: i % made.length,
      };
    });
    return { textures: made, placements: placed };
  }, []);

  useEffect(
    () => () => {
      textures.forEach((t) => t.dispose());
    },
    [textures],
  );

  useFrame((_state, delta) => {
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
            renderOrder={-3}
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

// --- supernovae -------------------------------------------------------------

/** Seconds a flare takes from ignition to gone. */
const NOVA_SECONDS = 4.5;
/** Quiet spell between flares: a surprise, not a light show. */
const NOVA_LULL_MIN = 14;
const NOVA_LULL_SPAN = 20;

/** A small radial flash texture, shared by every flare. */
function makeFlashTexture(): THREE.CanvasTexture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(237,235,246,0.7)");
  g.addColorStop(1, "rgba(237,235,246,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * Every so often one distant star goes up: a fast white flash that blooms and
 * dies over a few seconds while a thin shell ring expands through it. The
 * schedule and the sequence of sites are seeded, so the show is deterministic;
 * only the *clock* is live. Skipped entirely under reduced motion.
 */
function Supernovae() {
  const reduceMotion = useReduceMotion();
  const anchor = useRef<THREE.Group>(null);
  const flash = useRef<THREE.Mesh>(null);
  const ring = useRef<THREE.Mesh>(null);

  const state = useRef({
    rand: mulberry32(SKY_SEED ^ 0x5f), // one stream: sites and lulls together
    nextAt: 6, // first flare arrives soon after the scene settles
    startedAt: null as number | null,
  });

  const flashTexture = useMemo(() => makeFlashTexture(), []);
  useEffect(() => () => flashTexture.dispose(), [flashTexture]);

  useFrame(({ clock }) => {
    const group = anchor.current;
    if (!group) return;
    const s = state.current;
    const now = clock.elapsedTime;

    if (reduceMotion) {
      group.visible = false;
      s.startedAt = null;
      return;
    }

    if (s.startedAt === null) {
      if (now < s.nextAt) {
        group.visible = false;
        return;
      }
      // Ignite at a fresh seeded site on the star shell.
      const theta = s.rand() * Math.PI * 2;
      const phi = Math.acos(2 * s.rand() - 1);
      const r = FIELD_NEAR + s.rand() * (FIELD_FAR - FIELD_NEAR);
      group.position.set(
        Math.sin(phi) * Math.cos(theta) * r,
        Math.cos(phi) * r * 0.72,
        Math.sin(phi) * Math.sin(theta) * r,
      );
      s.startedAt = now;
    }

    const t = (now - s.startedAt) / NOVA_SECONDS;
    if (t >= 1) {
      s.startedAt = null;
      s.nextAt = now + NOVA_LULL_MIN + s.rand() * NOVA_LULL_SPAN;
      group.visible = false;
      return;
    }

    group.visible = true;
    // Fast attack, long exponential decay — the shape of a real light curve.
    const attack = Math.min(1, t / 0.06);
    const decay = Math.exp(-t * 4.2);
    const brightness = attack * decay;

    if (flash.current) {
      flash.current.scale.setScalar(2.5 + t * 9);
      (flash.current.material as THREE.MeshBasicMaterial).opacity = brightness;
    }
    if (ring.current) {
      ring.current.scale.setScalar(0.5 + t * 16);
      (ring.current.material as THREE.MeshBasicMaterial).opacity =
        0.5 * attack * (1 - t) ** 2;
    }
  });

  return (
    <group ref={anchor} visible={false}>
      <Billboard>
        <mesh ref={flash} renderOrder={-1}>
          <planeGeometry args={[1, 1]} />
          <meshBasicMaterial
            map={flashTexture}
            transparent
            opacity={0}
            depthWrite={false}
          />
        </mesh>
        {/* The expanding shell: the detail that says "supernova" rather than
            "blinking light". Halo-thin, like every other instrument ring. */}
        <mesh ref={ring} renderOrder={-1}>
          <ringGeometry args={[0.94, 1, 48]} />
          <meshBasicMaterial
            color={GL.starlight}
            transparent
            opacity={0}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      </Billboard>
    </group>
  );
}
