import { useThree } from "@react-three/fiber";
import { useEffect, useSyncExternalStore } from "react";
import * as THREE from "three";

import { ATMOSPHERE_SPHERE, PLANET_LAYERS, PLANET_SPHERE } from "./planetMaterials";
import { SHIP_GEOMETRY, createHullMaterial } from "./shipSurface";

/**
 * Compiles the cohort browser's shader programs ahead of time, off the critical
 * path, and **keeps them alive for the life of the canvas**.
 *
 * Opening `/cohorts` or Analytics' landing used to freeze the app for seconds.
 * Measured on the Windows development machine: a 4.4 s main-thread stall on the
 * first visit, with every other suspect (the fleet's meshes, the per-belt
 * lights, the geometry) removed and the number unchanged. It is one thing —
 * linking `PLANET_FRAGMENT`. That shader evaluates its height field three
 * times, each across a five-way world-type branch over unrolled four-octave
 * noise, and on Windows it goes through ANGLE to HLSL, whose compiler is slow
 * on exactly that shape. three links a program the first time a material is
 * *drawn* and then asks the driver whether it worked, and that question blocks
 * until the link finishes.
 *
 * Two facts make this module the fix rather than a rewrite of the shader:
 *
 *  - **The link does not have to block.** `compileAsync` submits the programs
 *    and polls `KHR_parallel_shader_compile` instead of asking the blocking
 *    question, so the driver works on its own threads while the app stays
 *    live. By the time anyone opens the browser the programs are simply there.
 *  - **Programs are refcounted** (`SharedCanvas.tsx`'s caution describes the
 *    same mechanism for the star). Leaving the route disposed every planet
 *    material, the count hit zero, three destroyed the programs, and the next
 *    visit linked them again. The materials below are never disposed, so the
 *    count never reaches zero and a program compiled once stays compiled.
 *
 * Both depend on the warm material producing the *same program key* as the
 * drawn one, which is why both are built from `PLANET_LAYERS`, on the same
 * kinds of object — and why the scene may contain **no lights**: light counts
 * are part of every program's key (`shipSurface.ts`), so a fleet's point light
 * would have made every program here a near miss.
 *
 * Mounted beside the backdrop in the permanent part of the canvas, so it runs
 * once per GL context and survives every navigation.
 */
export function ProgramWarmth() {
  const gl = useThree((state) => state.gl);
  const camera = useThree((state) => state.camera);

  useEffect(() => {
    // After first paint, not during it: the app's opening frames are the one
    // moment this work could still be felt on a driver without the parallel
    // compile extension.
    const timer = window.setTimeout(() => warm(gl, camera), WARM_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [gl, camera]);

  return null;
}

const WARM_DELAY_MS = 400;

/**
 * True once the cohort browser's programs are linked. Until then a world is
 * drawn as a flat stand-in (`CohortSky.tsx`), so a visit that beats the warm-up
 * — the app opened straight onto `/cohorts` — waits on a sky that is already
 * interactive instead of on a frozen window.
 */
export function useProgramsWarm(): boolean {
  return useSyncExternalStore(subscribe, () => ready);
}

let ready = false;
const listeners = new Set<() => void>();
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Held for the life of the page, per renderer — the references ARE the fix. */
const kept = new WeakMap<THREE.WebGLRenderer, THREE.Scene>();

function warm(gl: THREE.WebGLRenderer, camera: THREE.Camera): void {
  if (kept.has(gl)) return;
  const scene = buildWarmScene();
  kept.set(gl, scene);

  const done = () => {
    ready = true;
    for (const listener of listeners) listener();
  };
  // A failed warm-up must never leave the browser stuck on its stand-ins: the
  // worst case is the stall this module exists to remove, which is where the
  // app already was.
  gl.compileAsync(scene, camera).then(done, (err: unknown) => {
    console.warn("shader warm-up failed; programs will compile on first use", err);
    done();
  });
}

/**
 * One object per program, of the same KIND as the one that will be drawn —
 * `Mesh` vs `Points` and the geometry's attributes both reach the program key.
 * Uniform values are never uploaded (`compile` links, it does not draw), but
 * the declarations are complete so that a future three which validates them
 * has nothing to object to.
 */
function buildWarmScene(): THREE.Scene {
  const scene = new THREE.Scene();
  const colour = () => ({ value: new THREE.Color() });
  const vector = () => ({ value: new THREE.Vector3() });

  const surface = new THREE.ShaderMaterial({
    ...PLANET_LAYERS.surface,
    uniforms: {
      uTime: { value: 0 },
      uSeed: { value: 0 },
      uType: { value: 0 },
      uDeep: colour(),
      uEdge: colour(),
      uCore: colour(),
      uPeak: colour(),
      uAccent: colour(),
      uMineral: colour(),
      uLight: vector(),
      uLiveliness: { value: 0 },
    },
  });
  const atmosphere = new THREE.ShaderMaterial({
    ...PLANET_LAYERS.atmosphere,
    uniforms: { uAtmosphere: colour(), uLight: vector(), uStrength: { value: 0 } },
  });
  const ring = new THREE.ShaderMaterial({
    ...PLANET_LAYERS.ring,
    uniforms: {
      uCore: colour(),
      uAccent: colour(),
      uDeep: colour(),
      uLight: vector(),
      uCentre: vector(),
      uSeed: { value: 0 },
      uRadius: { value: 1 },
    },
  });
  const debris = new THREE.ShaderMaterial({
    ...PLANET_LAYERS.debris,
    uniforms: { uColour: colour(), uPixelRatio: { value: 1 } },
  });

  const grains = new THREE.BufferGeometry();
  grains.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3), 3));
  grains.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(1), 1));
  grains.setAttribute("aBright", new THREE.BufferAttribute(new Float32Array(1), 1));

  scene.add(
    new THREE.Mesh(PLANET_SPHERE, surface),
    new THREE.Mesh(ATMOSPHERE_SPHERE, atmosphere),
    new THREE.Mesh(new THREE.RingGeometry(1, 2, 8), ring),
    new THREE.Points(grains, debris),
    new THREE.Mesh(SHIP_GEOMETRY.fuselage, createHullMaterial(vector(), 1)),
  );
  return scene;
}
