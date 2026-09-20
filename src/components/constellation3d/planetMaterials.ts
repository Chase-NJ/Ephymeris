import * as THREE from "three";

import {
  ATMOSPHERE_FRAGMENT,
  DEBRIS_FRAGMENT,
  DEBRIS_VERTEX,
  PLANET_FRAGMENT,
  PLANET_VERTEX,
  RING_FRAGMENT,
  RING_VERTEX,
} from "./planetSurface";

/**
 * The four materials a world is drawn with — everything about them EXCEPT
 * their uniforms, declared once.
 *
 * Two callers build materials from this table and they must agree exactly:
 * `PlanetarySurface.tsx`, which draws the worlds, and `ProgramWarmth.tsx`, which
 * compiles the same programs ahead of time so that opening the cohort browser
 * does not. three keys a program on the shader source **and** on a parameter
 * list that includes `side`, `transparent` and friends
 * (`WebGLPrograms.getProgramCacheKey`), so a warm material that differed from
 * the drawn one in any of these would compile a program nothing ever uses —
 * and the stall it existed to remove would come back with no symptom except
 * the stall. One table, spread into both, is what keeps them from drifting.
 */
export const PLANET_LAYERS = {
  surface: {
    vertexShader: PLANET_VERTEX,
    fragmentShader: PLANET_FRAGMENT,
  },
  // Outside the spin: a fresnel shell is rotationally symmetric.
  atmosphere: {
    vertexShader: PLANET_VERTEX,
    fragmentShader: ATMOSPHERE_FRAGMENT,
    transparent: true,
    depthWrite: false,
    side: THREE.BackSide,
    blending: THREE.AdditiveBlending,
  },
  // The plane: structure, grain and the planet's shadow.
  ring: {
    vertexShader: RING_VERTEX,
    fragmentShader: RING_FRAGMENT,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  },
  // The debris: additive and without depth writes, like every particle field
  // in the scene, so grains in front of the planet's limb blend rather than cut.
  debris: {
    vertexShader: DEBRIS_VERTEX,
    fragmentShader: DEBRIS_FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  },
} as const satisfies Record<string, THREE.ShaderMaterialParameters>;

/**
 * The worlds' sphere, built once at unit radius and scaled per planet.
 *
 * The surface samples object space through a *normalised* position and the
 * shell is a fresnel term, so neither can tell a scaled unit sphere from one
 * built at size. 48 segments matches the star (`StellarSurface.tsx`): all of a
 * world's detail is in the fragment shader, and the silhouette at the sizes
 * the browser draws is indistinguishable from the 64 it used to be built at —
 * per planet, on every mount.
 */
export const PLANET_SPHERE = new THREE.SphereGeometry(1, 48, 48);
export const ATMOSPHERE_SPHERE = new THREE.SphereGeometry(1, 32, 32);
