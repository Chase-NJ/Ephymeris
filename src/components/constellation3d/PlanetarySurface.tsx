import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import {
  atmosphereStrength,
  planetPalette,
  typeIndex,
  type ResolvedAppearance,
} from "@/lib/cohorts/appearance";
import { hashString, mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { ATMOSPHERE_SPHERE, PLANET_LAYERS, PLANET_SPHERE } from "./planetMaterials";

/**
 * A cohort's world — the body a `SceneNode` in the cohort browser draws.
 *
 * Named for its shader module the way `StellarSurface` is for `starSurface.ts`;
 * the extra syllable is only there because a case-insensitive filesystem
 * cannot hold `PlanetSurface.tsx` beside `planetSurface.ts`.
 *
 * The sibling of `StellarSurface`, and built the same way: a shaded sphere,
 * a fresnel shell outside the spin, and everything eased by exponential lerp
 * rather than by a spring (the canvas's convention).
 *
 * Four layers, and each one is outside the spin unless it has a reason to be
 * inside it. Turning a rotationally symmetric shell is work with nothing to
 * show for it — the note `StellarSurface` leaves about its corona.
 *
 * **The light is a fixed direction, not a light.** See `planetSurface.ts`: the
 * scene contains no lights, by rule, because a light count is part of every
 * program's cache key.
 */
export function PlanetarySurface({
  radius,
  appearance,
  liveliness,
  seed,
}: {
  radius: number;
  appearance: ResolvedAppearance;
  /** 0 dormant … 1 worked on today. Drives spin rate and daylight together. */
  liveliness: number;
  /** Stable identity — seeds the axial tilt so a field of worlds doesn't stand
   *  upright in rows, which reads as a diagram rather than as a sky. */
  seed: string;
}) {
  const reduceMotion = useReduceMotion();
  const pixelRatio = useThree((state) => state.gl.getPixelRatio());

  const palette = useMemo(() => planetPalette(appearance), [appearance]);
  const axis = useMemo(() => axisFor(seed), [seed]);

  /*
   * Uniforms are created once and MUTATED, never rebuilt.
   *
   * Rebuilding the object on an appearance change would hand `shaderMaterial` a
   * new `uniforms` prop, which r3f applies by replacing the material — a
   * recompile, mid-drag, on every step of a hue slider. So the objects are
   * stable and the frame loop writes through them, which is also what makes
   * the editor's live preview free.
   */
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSeed: { value: appearance.seed * 0.001 },
      uType: { value: typeIndex(appearance.type) },
      uDeep: { value: palette.deep.clone() },
      uEdge: { value: palette.edge.clone() },
      uCore: { value: palette.core.clone() },
      uPeak: { value: palette.peak.clone() },
      uAccent: { value: palette.accent.clone() },
      uMineral: { value: palette.mineral.clone() },
      uLight: { value: LIGHT.clone() },
      uLiveliness: { value: liveliness },
    }),
    // Mount-only by design; every later change arrives through the frame loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const atmosphereUniforms = useMemo(
    () => ({
      uAtmosphere: { value: palette.atmosphere.clone() },
      uLight: { value: uniforms.uLight.value },
      uStrength: { value: atmosphereStrength(appearance) },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [uniforms],
  );

  const ringUniforms = useMemo(
    () => ({
      uCore: { value: palette.core.clone() },
      uAccent: { value: palette.accent.clone() },
      uDeep: { value: palette.deep.clone() },
      uLight: { value: uniforms.uLight.value },
      uCentre: { value: new THREE.Vector3() },
      uSeed: { value: appearance.seed * 0.001 },
      uRadius: { value: radius },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [uniforms, radius],
  );

  const debrisUniforms = useMemo(
    () => ({
      uColour: { value: palette.peak.clone() },
      uPixelRatio: { value: pixelRatio },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [uniforms],
  );
  useEffect(() => {
    debrisUniforms.uPixelRatio.value = pixelRatio;
  }, [debrisUniforms, pixelRatio]);

  /*
   * The materials, from the one table `ProgramWarmth` also builds from — that
   * shared origin is what makes these hit the programs it compiled ahead of
   * time rather than linking their own (`planetMaterials.ts`). Created once for
   * the same reason the uniforms are: a replaced material is a recompile.
   */
  const materials = useMemo(
    () => ({
      surface: new THREE.ShaderMaterial({ ...PLANET_LAYERS.surface, uniforms }),
      atmosphere: new THREE.ShaderMaterial({
        ...PLANET_LAYERS.atmosphere,
        uniforms: atmosphereUniforms,
      }),
      ring: new THREE.ShaderMaterial({ ...PLANET_LAYERS.ring, uniforms: ringUniforms }),
      debris: new THREE.ShaderMaterial({ ...PLANET_LAYERS.debris, uniforms: debrisUniforms }),
    }),
    [uniforms, atmosphereUniforms, ringUniforms, debrisUniforms],
  );
  useEffect(
    () => () => {
      for (const material of Object.values(materials)) material.dispose();
    },
    [materials],
  );

  /* The debris field — seeded from the world's own seed, so a re-roll
   * re-scatters it along with the plane it sits over. Spread through the same
   * annuli the plane draws (a little tighter, so points never float past the
   * plane's soft edge) with a small vertical scatter for thickness. Disposed
   * with the world. Built only for a world that HAS a ring: most do not, and
   * the field is drawn nowhere else. */
  const ringed = appearance.ring;
  const debris = useMemo(() => {
    if (!ringed) return null;
    const geometry = new THREE.BufferGeometry();
    const rand = mulberry32(hashString(`debris:${seed}:${Math.floor(appearance.seed)}`));
    const positions = new Float32Array(DEBRIS_COUNT * 3);
    const sizes = new Float32Array(DEBRIS_COUNT);
    const bright = new Float32Array(DEBRIS_COUNT);
    for (let i = 0; i < DEBRIS_COUNT; i += 1) {
      const t = 0.08 + rand() * 0.84; // inner .. outer, inside the plane's fade
      const r = radius * (RING_INNER + (RING_OUTER - RING_INNER) * t);
      const angle = rand() * Math.PI * 2;
      positions[i * 3] = Math.cos(angle) * r;
      positions[i * 3 + 1] = Math.sin(angle) * r;
      // Thickness: most of the field lies near the plane, a few grains stray.
      const lift = (rand() - 0.5) * 2;
      positions[i * 3 + 2] = lift * lift * lift * radius * 0.09;
      sizes[i] = 0.6 + rand() * 1.4;
      bright[i] = 0.08 + rand() * 0.22;
    }
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute("aBright", new THREE.BufferAttribute(bright, 1));
    return geometry;
  }, [ringed, seed, appearance.seed, radius]);
  useEffect(() => () => debris?.dispose(), [debris]);

  // Owned here rather than declared as JSX: the mesh that wears it carries
  // `dispose={null}` for its shared-table material, which would otherwise leave
  // this buffer undisposed on every visit to the browser.
  const ringPlane = useMemo(
    () =>
      ringed ? new THREE.RingGeometry(radius * RING_INNER, radius * RING_OUTER, 128) : null,
    [ringed, radius],
  );
  useEffect(() => () => ringPlane?.dispose(), [ringPlane]);

  const spin = useRef<THREE.Group>(null);
  const ringGroup = useRef<THREE.Group>(null);

  useFrame((_state, raw) => {
    // Bounded like every other time-integrated animation here: an unclamped
    // delta is wall-clock, so one stalled frame jumps this forward by the
    // whole stall (`CameraRig`'s `MAX_FRAME_SECONDS`).
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    const moving = !reduceMotion;

    // Advancing `uTime` is what animates the bands, the storms and the lava
    // cracks. Frozen rather than hidden under reduced motion — the world is
    // still fully drawn, it just stops weathering.
    if (moving) uniforms.uTime.value += delta;

    /*
     * A dormant cohort barely turns. This is the same reading as the day-side
     * brightness below, deliberately: "nobody has been here" should land as one
     * impression rather than as two facts the eye has to reconcile. The floor
     * is not zero — `livelinessFor` never returns it — because a frozen world
     * beside turning ones reads as a rendering fault.
     */
    if (moving && spin.current) {
      spin.current.rotation.y += delta * SPIN_BASE * (0.35 + 0.65 * liveliness);
    }
    // The ring turns the other way and much slower: it is debris on its own
    // orbit, not paint on the planet.
    if (moving && ringGroup.current) {
      ringGroup.current.rotation.z -= delta * SPIN_BASE * 0.18;
    }

    // Ease toward whatever the appearance now says. Reached through the frame
    // loop rather than through props so a hue drag never rebuilds a material.
    const k = Math.min(1, delta * 6);
    uniforms.uDeep.value.lerp(palette.deep, k);
    uniforms.uEdge.value.lerp(palette.edge, k);
    uniforms.uCore.value.lerp(palette.core, k);
    uniforms.uPeak.value.lerp(palette.peak, k);
    uniforms.uAccent.value.lerp(palette.accent, k);
    uniforms.uMineral.value.lerp(palette.mineral, k);
    atmosphereUniforms.uAtmosphere.value.lerp(palette.atmosphere, k);
    ringUniforms.uCore.value.lerp(palette.core, k);
    ringUniforms.uAccent.value.lerp(palette.accent, k);
    ringUniforms.uDeep.value.lerp(palette.deep, k);
    debrisUniforms.uColour.value.lerp(palette.peak, k);

    // Stepped rather than eased: a type is a different world, not a warmer one,
    // and interpolating between two surface functions produces neither.
    uniforms.uType.value = typeIndex(appearance.type);
    uniforms.uSeed.value = appearance.seed * 0.001;
    ringUniforms.uSeed.value = appearance.seed * 0.001;
    uniforms.uLiveliness.value += (liveliness - uniforms.uLiveliness.value) * k;
    atmosphereUniforms.uStrength.value +=
      (atmosphereStrength(appearance) - atmosphereUniforms.uStrength.value) * k;
  });

  return (
    <group>
      {/* Tilt outside, spin inside — a world with an inclined axis, the way
          `StellarSurface` inclines a star. The surface pattern rides along
          because the shader samples object space; the terminator does not,
          because it works off the world normal. */}
      <group rotation={[axis.tiltX, 0, axis.tiltZ]}>
        <group ref={spin}>
          {/* A shared unit sphere, scaled — see `planetMaterials.ts`. The
              geometry is passed as a prop, so it is kept out of r3f's disposal
              with `dispose={null}` and the material, which r3f would then also
              skip, is owned below. */}
          <mesh scale={radius} geometry={PLANET_SPHERE} material={materials.surface} dispose={null} />
        </group>
      </group>

      {/* Outside the spin: a fresnel shell is rotationally symmetric. */}
      <mesh
        scale={radius * 1.045}
        geometry={ATMOSPHERE_SPHERE}
        material={materials.atmosphere}
        dispose={null}
      />

      {debris && (
        // Tilted with the axis, so the ring sits in the world's equatorial
        // plane rather than at an angle of its own — the thing that makes a
        // ring read as belonging to the planet it circles.
        <group rotation={[axis.tiltX + Math.PI / 2, 0, axis.tiltZ]}>
          <group ref={ringGroup}>
            {/* The plane: structure, grain and the planet's shadow. */}
            <mesh geometry={ringPlane!} material={materials.ring} dispose={null} />
            {/* The debris: the thickness a plane cannot have. */}
            <points geometry={debris} material={materials.debris} dispose={null} />
          </group>
        </group>
      )}
    </group>
  );
}

/**
 * Where the light comes from, in world space.
 *
 * One direction for every planet in the field, and that is the point: a sky
 * whose worlds are each lit from their own angle reads as a collage. Slightly
 * above and to the left of the camera's default approach, so a planet at rest
 * shows a terminator rather than a fully lit disc — a fully lit sphere has no
 * shading to say it is a sphere.
 */
const LIGHT = new THREE.Vector3(-0.55, 0.42, 0.72).normalize();

/** Radians per second at full liveliness. About 40 s a turn — slow enough to
 *  read as a planet rather than a top, fast enough to see. */
const SPIN_BASE = 0.16;

/** The ring's extent in radii. Shared by the plane and the debris field so
 *  they describe one object. */
const RING_INNER = 1.45;
const RING_OUTER = 2.4;

/** Enough to read as a field at the overview without being a haze up close.
 *  Each is one point sprite; the whole field is a single draw. */
const DEBRIS_COUNT = 420;

/** Axial tilt, seeded so a field of worlds doesn't stand upright in rows. */
function axisFor(seed: string): { tiltX: number; tiltZ: number } {
  const rand = mulberry32(hashString(`axis:${seed}`));
  return { tiltX: (rand() - 0.5) * 0.5, tiltZ: (rand() - 0.5) * 0.5 };
}
