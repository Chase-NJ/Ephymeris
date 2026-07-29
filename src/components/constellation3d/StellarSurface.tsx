import { useFrame } from "@react-three/fiber";
import { useMemo } from "react";
import * as THREE from "three";

import {
  CORONA_FRAGMENT,
  CORONA_VERTEX,
  STAR_FRAGMENT,
  STAR_VERTEX,
  rampColors,
  temperatureFor,
} from "./starSurface";
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
 */
export function StellarSurface({
  radius,
  accuracy,
  churn = true,
}: {
  radius: number;
  accuracy: number | null;
  churn?: boolean;
}) {
  const reduceMotion = useReduceMotion();

  // Born at the earned temperature — the lerp below smooths *changes*, but a
  // star that already knows its accuracy should not flash chance-red on every
  // mount before warming to what the data long since established.
  const uniforms = useMemo(() => {
    const initial = rampColors(temperatureFor(accuracy));
    return {
      uTime: { value: 0 },
      uCore: { value: initial.core.clone() },
      uEdge: { value: initial.edge.clone() },
      uActivity: { value: 1 },
    };
    // Mount-only by design: later accuracy changes arrive via the eased lerp.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Shares the *same* Color instance as the surface, so the rim tracks the
  // temperature for free — lerping one below updates both.
  const coronaUniforms = useMemo(
    () => ({ uCore: { value: uniforms.uCore.value }, uStrength: { value: 0.5 } }),
    [uniforms],
  );

  const target = useMemo(() => rampColors(temperatureFor(accuracy)), [accuracy]);

  useFrame((_state, delta) => {
    const active = churn && !reduceMotion;
    if (active) uniforms.uTime.value += delta;
    uniforms.uActivity.value = active ? 1 : 0;
    // Ease toward the earned temperature — fast enough to notice within a few
    // trials, slow enough that one lucky trial doesn't recolour the star.
    const k = Math.min(1, delta * 1.2);
    uniforms.uCore.value.lerp(target.core, k);
    uniforms.uEdge.value.lerp(target.edge, k);
  });

  return (
    <group>
      <mesh>
        <sphereGeometry args={[radius, 48, 48]} />
        <shaderMaterial
          vertexShader={STAR_VERTEX}
          fragmentShader={STAR_FRAGMENT}
          uniforms={uniforms}
        />
      </mesh>
      <mesh scale={1.35}>
        <sphereGeometry args={[radius, 32, 32]} />
        <shaderMaterial
          vertexShader={CORONA_VERTEX}
          fragmentShader={CORONA_FRAGMENT}
          uniforms={coronaUniforms}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}
