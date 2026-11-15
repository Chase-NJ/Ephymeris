import { useFrame } from "@react-three/fiber";
import { MAX_FRAME_SECONDS } from "./CameraRig";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import {
  CORONA_FRAGMENT,
  CORONA_VERTEX,
  STAR_FRAGMENT,
  STAR_VERTEX,
  rampColors,
  sizeFor,
  temperatureFor,
} from "./starSurface";
import { seededRandom } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * A performance-tinted star: granulated surface plus a rim-only chromosphere,
 * both coloured by the temperature its accuracy earns (`starSurface.ts`).
 *
 * Shared by the two views that put accuracy on a star — Mission Control (an
 * animal's pooled rolling accuracy, live) and Debug Mode (the mean recorded
 * accuracy of the box's assigned animals) — so the temperature vocabulary
 * stays one vocabulary. The colour is animated toward its target rather than
 * snapped, so a run of good trials warms the star visibly instead of making
 * it flicker between classes trial by trial.
 *
 * `churn` keeps each view's motion grammar intact: Mission Control's lit
 * stars always churn, while Debug stills the surface of a box that isn't
 * detected — stillness is the status, carried into the photosphere itself.
 * Reduced motion stills every surface regardless.
 *
 * `dim` is the *other* half of that status in Debug: an undetected box's star
 * burns down to a fraction of its earned brightness. It is a scale on the ramp
 * colours rather than an opacity or a shader branch, which buys three things —
 * the corona shares the same `Color` instance and dims with the surface for
 * free, the temperature stays legible (a dim K-star is still red, a dim A-star
 * still blue), and the existing colour lerp turns connect/disconnect into a
 * fade-up/fade-down instead of a pop.
 *
 * Temperature is read **three** ways, all from the one ramp position: colour,
 * size (`sizeFor` — hotter is bigger, as on the main sequence), and nothing
 * else. Rotation is not one of them: every star turns at its own seeded rate,
 * because a star that turns is a star, not a status.
 */
export function StellarSurface({
  radius,
  accuracy,
  churn = true,
  dim = false,
  seed,
}: {
  radius: number;
  accuracy: number | null;
  churn?: boolean;
  dim?: boolean;
  /**
   * Stable identity for this star — the box number in Debug, the animal id in
   * Mission Control. Seeds the rotation rate and axis so six stars in one sky
   * don't turn in lockstep, which reads as a mechanism rather than as six
   * independent objects. Optional: without one every star gets the same
   * middling spin, which is a fine default and no caller's problem.
   */
  seed?: string | undefined;
}) {
  const reduceMotion = useReduceMotion();

  // Born at the earned temperature *and* the current brightness — the lerp
  // below smooths *changes*, but a star that already knows its accuracy should
  // not flash chance-red on every mount before warming to what the data long
  // since established, and a box already known to be absent should not flare to
  // full and fade back on every navigation.
  const uniforms = useMemo(() => {
    const initial = brightened(accuracy, dim);
    return {
      uTime: { value: 0 },
      uCore: { value: initial.core },
      uEdge: { value: initial.edge },
      uActivity: { value: 1 },
    };
    // Mount-only by design: later accuracy and brightness changes arrive via
    // the eased lerp.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Shares the *same* Color instance as the surface, so the rim tracks the
  // temperature for free — lerping one below updates both.
  const coronaUniforms = useMemo(
    () => ({
      uCore: { value: uniforms.uCore.value },
      uStrength: { value: 0.5 },
    }),
    [uniforms],
  );

  /*
   * Materials as objects, handed over with `material={…}` — not JSX
   * `<shaderMaterial uniforms={…}>`, which r3f copies entry by entry into the
   * material, so the frame callback's `uTime`/`uActivity` writes never reached
   * the GPU and every surface sat frozen (`ARCHITECTURE.md#one-sky`).
   */
  const surfaceMaterial = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: STAR_VERTEX,
        fragmentShader: STAR_FRAGMENT,
        uniforms,
      }),
    [uniforms],
  );
  const coronaMaterial = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: CORONA_VERTEX,
        fragmentShader: CORONA_FRAGMENT,
        uniforms: coronaUniforms,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    [coronaUniforms],
  );
  useEffect(() => () => {
    surfaceMaterial.dispose();
    coronaMaterial.dispose();
  }, [surfaceMaterial, coronaMaterial]);

  const target = useMemo(() => brightened(accuracy, dim), [accuracy, dim]);

  const rotation = useMemo(() => rotationFor(seed), [seed]);
  const spin = useRef<THREE.Group>(null);

  /*
   * The temperature's *other* reading, eased on the same curve as the colours so
   * warming and swelling are one change rather than two.
   *
   * **Born at the size this star was last shown at, not at the size its current
   * accuracy earns.** The two views feed different numbers — Mission Control a
   * live rolling accuracy, the rig views the recorded mean across every scored
   * session — so the same box legitimately deserves a different size in each.
   * Sized from scratch on mount, that difference arrives as a pop at the exact
   * moment the camera is easing out of a close-up of it, and reads as the star
   * jumping. Remembered, the star simply keeps its size across the handoff and
   * grows or shrinks into the new view's answer.
   *
   * Placed by a layout effect rather than a `scale` prop, so `useFrame` below is
   * the group's only writer. As a prop, r3f's diffing would decide when it got
   * re-applied, and a later edit could silently restate the birth size on every
   * telemetry render and fight the lerp — in the one view whose accuracy is live.
   */
  const body = useRef<THREE.Group>(null);
  const targetSize = sizeFor(temperatureFor(accuracy));
  const sizeRef = useRef(remembered(seed) ?? targetSize);
  useLayoutEffect(() => {
    body.current?.scale.setScalar(sizeRef.current);
  }, []);

  useFrame((_state, raw) => {
    // Bounded like every other time-integrated animation: an unclamped
    // `delta` is wall-clock, so one stalled frame jumps this forward by the
    // whole stall (`CameraRig`'s `MAX_FRAME_SECONDS`).
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    const active = churn && !reduceMotion;
    if (active) uniforms.uTime.value += delta;
    uniforms.uActivity.value = active ? 1 : 0;

    // Gated on exactly what the churn is: an undetected box's star is frozen,
    // which is the status carried into the photosphere itself, and reduced
    // motion stills every star regardless. A rotating star that had stopped
    // boiling would say two different things about the same box.
    if (active && spin.current)
      spin.current.rotation.y += delta * rotation.rate;

    // Ease toward the earned temperature — fast enough to notice within a few
    // trials, slow enough that one lucky trial doesn't recolour the star.
    const k = Math.min(1, delta * 1.2);
    uniforms.uCore.value.lerp(target.core, k);
    uniforms.uEdge.value.lerp(target.edge, k);
    sizeRef.current += (targetSize - sizeRef.current) * k;
    body.current?.scale.setScalar(sizeRef.current);
    if (seed !== undefined) displayedScale.set(seed, sizeRef.current);
  });

  return (
    // Scaled as a whole, so the chromosphere keeps its proportion to the
    // photosphere at every temperature. This composes with the hover swell
    // `StarNode` applies to the group above it, which is what we want:
    // hovering enlarges by the same factor whatever size the star already is.
    <group ref={body}>
      {/* Tilt outside, spin inside, so the axis is inclined the way a real
          star's is rather than standing perfectly upright in every slot. The
          granulation rides along because the shader samples object space
          (`starSurface.ts`); limb darkening does not, so the star stays lit
          toward the camera as it turns. */}
      <group rotation={[rotation.tiltX, 0, rotation.tiltZ]}>
        <group ref={spin}>
          <mesh material={surfaceMaterial}>
            <sphereGeometry args={[radius, 48, 48]} />
          </mesh>
        </group>
      </group>

      {/* Outside the spin deliberately: the corona is a rotationally symmetric
          fresnel rim, so turning it is work with nothing to show for it. */}
      <mesh scale={1.35} material={coronaMaterial}>
        <sphereGeometry args={[radius, 32, 32]} />
      </mesh>
    </group>
  );
}

/**
 * The size each star was last drawn at, keyed by its `seed`.
 *
 * Module-level for the reason the shared camera and its pivot are
 * (`Scene.tsx`): a star's *displayed* size is a property of the star, not of
 * whichever component instance happens to be showing it. Views swap constantly —
 * the same box is drawn by Mission Control, then by the Dashboard, then by Debug
 * — and each swap is a fresh mount of this component. Without a memory, every
 * one of them restarts the ease from its own answer.
 *
 * Bounded by the number of boxes, and stale entries cost a number each. A star
 * with no `seed` opts out and simply starts at its target.
 */
const displayedScale = new Map<string, number>();

function remembered(seed: string | undefined): number | undefined {
  return seed === undefined ? undefined : displayedScale.get(seed);
}

/**
 * How fast, and about what axis, a star turns.
 *
 * Slow on purpose — a full revolution takes the better part of two minutes. The
 * rotation has to be unmistakable when the camera has flown in and the star
 * fills the frame, and completely unobtrusive at overview range where six of
 * them are on screen at once beside orbiting cage-ships. Anything faster stops
 * reading as a star and starts reading as a loading spinner.
 */
const SPIN_BASE = 0.06;
const SPIN_SPREAD = 0.05;

function rotationFor(seed: string | undefined): {
  rate: number;
  tiltX: number;
  tiltZ: number;
} {
  if (seed === undefined) return { rate: SPIN_BASE, tiltX: 0.3, tiltZ: 0.1 };
  // Seeded from the star's own identity, the same way `Orbiters` seeds its
  // craft: a box's star turns the same way every time the app is opened, and
  // adding a seventh box never changes how the first six turn.
  const rand = seededRandom(`spin:${seed}`);
  return {
    rate: SPIN_BASE + rand() * SPIN_SPREAD,
    tiltX: 0.18 + rand() * 0.3,
    tiltZ: (rand() - 0.5) * 0.45,
  };
}

/**
 * How far an undetected box's star burns down. Low enough to read instantly as
 * "this one is dark" beside a lit neighbour, high enough that the star is still
 * a star with a legible colour — a box that is merely unplugged has not stopped
 * being the box whose animals scored what they scored.
 */
const DIM_LEVEL = 0.3;

/** The ramp colours at the given accuracy, scaled to the current brightness.
 *  Fresh `Color` instances every call (`rampColors` clones), so scaling them in
 *  place can never reach back into the shared ramp. */
function brightened(
  accuracy: number | null,
  dim: boolean,
): { core: THREE.Color; edge: THREE.Color } {
  const ramp = rampColors(temperatureFor(accuracy));
  if (dim) {
    ramp.core.multiplyScalar(DIM_LEVEL);
    ramp.edge.multiplyScalar(DIM_LEVEL);
  }
  return ramp;
}
