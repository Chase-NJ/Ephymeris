import { GLSL_NOISE } from "./starSurface";

/**
 * The planet-surface material for the cohort browser (`cohorts.md` §5).
 *
 * A sibling of `starSurface.ts`, written the same way and under the same
 * licence: `dashboard.md` §2.2 forbids gradients and glow, and this is the
 * **second** bounded exception to it. The first was the star, allowed because
 * its colour is its temperature is an animal's pooled accuracy. A planet earns
 * it the same way — three of its four dimensions are readings, not decoration:
 *
 *   size            the cohort's roster
 *   spin + daylight  how recently anyone worked on it
 *   ships in orbit   its home cages
 *   type, hue, ring  the operator's own, and identity IS information: picking
 *                    "the banded amber one" out of twelve at 8am beats reading
 *                    twelve similar names
 *
 * The exception stays inside this file, `PlanetarySurface.tsx` and the
 * browser's scene; nothing in the 2D chrome gains a gradient or a glow, and
 * `PlanetDisc` — the flat mark that stands in for a planet at 32px — is drawn
 * in the matte register like every other icon.
 *
 * **Lighting is a uniform, never a light.** The terminator comes from `uLight`,
 * exactly as the star's limb darkening comes from the view vector. The scene
 * contains no lights at all, and must not gain one: a light's mere presence is
 * part of every program's cache key, which is what made the per-belt light the
 * ships once carried relink the whole scene whenever a fleet came or went, and
 * what would make the programs `ProgramWarmth.tsx` links ahead of time miss
 * (`shipSurface.ts`). This shader is the expensive one — seconds to link on
 * Windows — so it is the one that most needs that warm-up to hit.
 *
 * **Topography is lit, not painted.** The first version coloured elevation and
 * left it at that, and every rocky world came out a flat tan: a height field
 * with no shading is a map, not terrain. The surface now perturbs its normal by
 * the height field's gradient before lighting, so a slope facing the light is
 * bright and the slope behind it is in shadow — which is the only thing that
 * makes a bump read as a mountain rather than as a stain.
 */

/**
 * **`vPos` is object space; `vWorld` is not, and the split is the point.**
 *
 * The surface pattern is sampled from the untransformed vertex position, so it
 * is rigidly attached to the sphere and rides the rotation `PlanetarySurface`
 * applies. The terminator works off the world normal instead, so the lit side
 * stays where the light is while the continents turn past it — which is what
 * makes the thing read as a rotating planet rather than as a sphere with a
 * moving texture. `STAR_VERTEX` makes the same split for granulation versus
 * limb darkening.
 */
export const PLANET_VERTEX = /* glsl */ `
  varying vec3 vPos;
  varying vec3 vWorld;
  varying vec3 vView;
  void main() {
    vPos = position;
    vWorld = normalize(mat3(modelMatrix) * normal);
    vView = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const PLANET_FRAGMENT = /* glsl */ `
  // highp, unlike the star: the seed offsets the noise field by up to ~100
  // units, and at mediump the fractional part that value noise lives on is
  // gone by then — every re-rolled world would collapse to the same blocks.
  precision highp float;

  // three prepends this to the VERTEX stage only. Declaring it here binds the
  // same program uniform, which is what the bump normal needs to reach world
  // space and agree with a light that lives there.
  uniform mat4 modelMatrix;

  uniform float uTime;
  uniform float uSeed;
  uniform int   uType;       // 0 rocky, 1 gas, 2 ice, 3 ocean, 4 lava
  uniform vec3  uDeep;       // the lowest ground: sea floor, crust, shadowed bands
  uniform vec3  uEdge;       // low ground
  uniform vec3  uCore;       // high ground, cloud tops
  uniform vec3  uPeak;       // the highest ground: snowline, cloud crests
  uniform vec3  uAccent;     // the one bright thing: caps, foam, cracks, a storm
  uniform vec3  uMineral;    // a second hue, in patches — what stops one colour reading as paint
  uniform vec3  uLight;      // direction TO the light, world space
  uniform float uLiveliness; // 0 dormant .. 1 worked on today
  varying vec3 vPos;
  varying vec3 vWorld;
  varying vec3 vView;

  ${GLSL_NOISE}

  // Ridged fBm: the CREASES of the field rather than its peaks. Sharp valleys
  // and soft summits, which is what eroded ground and ice fractures look like.
  float ridged(vec3 p) {
    float sum = 0.0;
    float amp = 0.55;
    for (int i = 0; i < 4; i++) {
      float n = 1.0 - abs(noise(p) * 2.0 - 1.0);
      sum += amp * n * n;
      p *= 2.07;
      amp *= 0.5;
    }
    return sum;
  }

  // The height field, by world type. Also used for the bump normal below, so
  // it has to be a pure function of position — no view terms in here.
  float terrain(vec3 p, float drift) {
    if (uType == 1) {
      // Gas: domain-warped bands. Height here is cloud-top height.
      float warp = fbm(p * 1.4 + vec3(drift, 0.0, -drift)) - 0.5;
      float bands = sin((p.y * 0.38 + warp * 0.55) * 9.0) * 0.5 + 0.5;
      float curl = fbm(p * 3.6 + vec3(0.0, drift * 2.2, 0.0));
      return clamp(bands * 0.72 + curl * 0.36, 0.0, 1.0);
    } else if (uType == 2) {
      float h = fbm(p * 1.7);
      float crack = ridged(p * 3.1);
      return clamp(h * 0.55 + 0.3 - crack * 0.12, 0.0, 1.0);
    } else if (uType == 3) {
      // Ocean: continents are a THRESHOLD of the field with relief only above
      // the waterline — so the sea is dead flat and the land is not, which is
      // what a coastline at the terminator needs to read as a coastline.
      float h = fbm(p * 1.9);
      float land = smoothstep(0.48, 0.53, h);
      float relief = fbm(p * 4.3) * 0.5 + ridged(p * 6.0) * 0.5;
      return 0.48 + land * (0.12 + relief * 0.4);
    } else if (uType == 4) {
      float h = fbm(p * 2.1);
      float crack = ridged(p * 2.4 + vec3(0.0, drift * 0.5, 0.0));
      return clamp(h * 0.6 + 0.2 - crack * 0.25, 0.0, 1.0);
    }
    // Rocky: two scales of relief, ridged at the fine end so the highlands
    // are creased rather than blobby.
    float continents = fbm(p * 1.5);
    float hills = ridged(p * 4.2);
    return clamp((continents - 0.4) * 1.6 + 0.5 + (hills - 0.45) * 0.55, 0.0, 1.0);
  }

  void main() {
    // The seed offsets the whole field rather than scaling it, so a re-roll
    // moves the weather without changing how big the features are — a cohort
    // stays recognisably itself across a re-roll.
    vec3 n = normalize(vPos);
    vec3 p = n * 2.6 + vec3(uSeed);
    float drift = uTime * 0.012;
    float lat = n.y;

    float h = terrain(p, drift);

    // --- the bump normal ---------------------------------------------------
    // Sample the height field a little way along the sphere's tangent and
    // bitangent, and tilt the normal by the difference. This is finite-
    // difference bump mapping in object space; it goes into world space with
    // the model matrix so the shading agrees with a light that lives there.
    vec3 up = abs(n.y) > 0.92 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0);
    vec3 tangent = normalize(cross(up, n));
    vec3 bitangent = cross(n, tangent);
    float eps = 0.018;
    float hx = terrain(normalize(n + tangent * eps) * 2.6 + vec3(uSeed), drift);
    float hy = terrain(normalize(n + bitangent * eps) * 2.6 + vec3(uSeed), drift);
    // Relief strength by type: gas giants are soft, rock is not. Scaled so a
    // typical slope tilts the normal by a few tens of degrees, not ninety —
    // the first cut tilted it so hard that most of every world sat in its
    // own hills' shadow and the whole field read as dark crescents.
    float relief = uType == 1 ? 0.35 : (uType == 3 ? 0.9 : 1.2);
    // Clamped: the ridged octaves can step a long way over one eps, and an
    // unbounded derivative tilts the normal past the horizon — which reads
    // as a hole in the daylight, not as a mountain.
    float dx = clamp((hx - h) / eps, -6.0, 6.0) * relief * 0.03;
    float dy = clamp((hy - h) / eps, -6.0, 6.0) * relief * 0.03;
    vec3 bumped = normalize(n - tangent * dx - bitangent * dy);
    vec3 Nw = normalize(mat3(modelMatrix) * bumped);

    // --- colour ----------------------------------------------------------
    // A four-stop ramp rather than a two-stop mix. Two stops was the whole
    // reason everything read as one flat tan: with nothing between "low" and
    // "high" there is no lowland, no upland and no snowline, just a tint.
    vec3 base;
    if (h < 0.35)      base = mix(uDeep, uEdge, smoothstep(0.0, 0.35, h));
    else if (h < 0.7)  base = mix(uEdge, uCore, smoothstep(0.35, 0.7, h));
    else               base = mix(uCore, uPeak, smoothstep(0.7, 1.0, h));

    // Mineral patches: a second hue in slow, large blotches. One colour
    // family across a whole world is paint; two is geology.
    float mineral = smoothstep(0.42, 0.68, fbm(p * 0.9 + vec3(31.7)));
    base = mix(base, uMineral, mineral * 0.3);

    float accentMask = 0.0;
    float emissive = 0.0;
    if (uType == 1) {
      // One storm: the brightest cell in a slow, coarse field. Never more than
      // one, because a planet covered in spots reads as noise.
      float storm = fbm(p * 1.1 - vec3(drift * 0.6));
      accentMask = smoothstep(0.72, 0.86, storm);
    } else if (uType == 2) {
      accentMask = smoothstep(0.82, 0.98, ridged(p * 3.1));
    } else if (uType == 3) {
      // Foam sits in the narrow band on either side of the waterline.
      float raw = fbm(p * 1.9);
      accentMask = smoothstep(0.47, 0.49, raw) * (1.0 - smoothstep(0.52, 0.55, raw));
    } else if (uType == 4) {
      float crack = ridged(p * 2.4 + vec3(0.0, drift * 0.5, 0.0));
      accentMask = smoothstep(0.78, 0.96, crack);
      emissive = accentMask * (0.55 + 0.45 * sin(uTime * 0.9 + uSeed));
    } else {
      // Polar caps by latitude, and a snowline: the highest ground goes white
      // whatever the hue, which is what makes a rocky world read as having an
      // UP as well as an around.
      float cap = smoothstep(0.62, 0.86, abs(lat) - fbm(p * 4.0) * 0.16);
      float snow = smoothstep(0.86, 0.96, h);
      accentMask = max(cap, snow * 0.7);
    }
    base = mix(base, uAccent, clamp(accentMask, 0.0, 1.0));

    // --- light -----------------------------------------------------------
    vec3 L = normalize(uLight);
    float lambert = dot(Nw, L);
    // The terminator from the UNBUMPED normal, so relief cannot punch daylight
    // through to the night side; the bumped one shades within the day.
    float day = smoothstep(-0.25, 0.45, dot(normalize(vWorld), L));
    // Slope shading is a MODULATION of daylight, not a second terminator: a
    // slope facing away from the light is dimmer than one facing it, and
    // neither is dark. Kept in a narrow band so topography reads as relief
    // rather than as blotches of night scattered across the day side.
    float slope = clamp(lambert * 0.5 + 0.5, 0.0, 1.0);
    float shade = 0.7 + 0.5 * slope;

    // The night side is TINTED, never black. A black hemisphere against a dark
    // sky is a hole punched in the scene, and the planet stops being a sphere.
    // How dark it gets is the liveliness reading: a cohort nobody has touched
    // in a fortnight sits mostly in its own shadow.
    float floorLight = 0.14 + 0.16 * uLiveliness;
    float lit = floorLight + (0.7 + 0.45 * uLiveliness) * day * shade;

    // A cool rim on the lit limb — the atmosphere seen edge-on from inside.
    float facing = clamp(dot(normalize(vView), vec3(0.0, 0.0, 1.0)), 0.0, 1.0);
    float rim = pow(1.0 - facing, 3.0) * day * 0.3;

    // Ocean gets a sun glint on the water only — the one thing that says
    // "liquid" at this scale.
    float glint = 0.0;
    if (uType == 3 && h < 0.485) {
      vec3 V = normalize(cameraPosition - (modelMatrix * vec4(vPos, 1.0)).xyz);
      vec3 H = normalize(L + V);
      glint = pow(max(dot(normalize(vWorld), H), 0.0), 48.0) * day * 0.55;
    }

    vec3 colour = base * lit + uAccent * emissive * 0.8 + uAccent * rim + vec3(glint);
    gl_FragColor = vec4(colour, 1.0);
  }
`;

/**
 * The atmosphere shell — `CORONA_FRAGMENT` with a light term.
 *
 * Same figure as the star's chromosphere and for the same reason it isn't a
 * bloom filter: brightest where the sphere is edge-on, absent at the centre.
 * What differs is that a planet's air is only lit where its day side is, so the
 * shell fades around the back — without that it reads as a ring the planet
 * happens to sit inside.
 */
export const ATMOSPHERE_FRAGMENT = /* glsl */ `
  precision mediump float;
  uniform vec3  uAtmosphere;
  uniform vec3  uLight;
  uniform float uStrength;
  varying vec3 vWorld;
  varying vec3 vView;
  void main() {
    float facing = clamp(dot(normalize(vView), vec3(0.0, 0.0, 1.0)), 0.0, 1.0);
    float rim = pow(1.0 - facing, 2.4);
    float lambert = dot(normalize(vWorld), normalize(uLight));
    // Wider than the surface terminator: air scatters light around the limb,
    // which is why a real planet's atmosphere is visible slightly past its
    // sunset line.
    float day = smoothstep(-0.55, 0.5, lambert);
    gl_FragColor = vec4(uAtmosphere, rim * uStrength * day);
  }
`;

/**
 * The ring plane: several distinct annuli, grain, and the planet's shadow.
 *
 * The first version was one band of low-frequency noise and read as a picture
 * of a ring pasted around the planet. Three things fix that, and each is a
 * separate term below: **structure** (a handful of annuli with real gaps
 * between them, so it is a ring *system*), **grain** (high-frequency noise
 * along both the radius and the angle, so it is made of something), and
 * **shadow** (the planet's, cast across the far side, which is the figure that
 * says the two objects share a space). `PlanetarySurface` lays a field of
 * debris points over this plane for the third dimension the plane cannot have.
 *
 * `vUv.x` runs across a `ringGeometry`'s width, inner to outer, which is what
 * lets the annuli be a 1D function of it.
 */
export const RING_VERTEX = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vRingWorld;
  varying vec3 vRingLocal;
  void main() {
    vUv = uv;
    vRingLocal = position;
    vRingWorld = (modelMatrix * vec4(position, 1.0)).xyz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const RING_FRAGMENT = /* glsl */ `
  precision mediump float;
  uniform vec3  uCore;
  uniform vec3  uAccent;
  uniform vec3  uDeep;
  uniform vec3  uLight;
  uniform vec3  uCentre;
  uniform float uSeed;
  uniform float uRadius;
  varying vec2 vUv;
  varying vec3 vRingWorld;
  varying vec3 vRingLocal;

  ${GLSL_NOISE}

  void main() {
    float t = vUv.x;                                  // 0 inner edge .. 1 outer
    float angle = atan(vRingLocal.y, vRingLocal.x);   // around the ring

    // STRUCTURE — the annuli. Four to six distinct bands with gaps, from a
    // low-frequency 1D field thresholded hard. The threshold is what makes a
    // gap a gap rather than a dimmer patch.
    float coarse = fbm(vec3(t * 5.5 + uSeed, uSeed * 0.7, 0.0));
    float annuli = smoothstep(0.38, 0.46, coarse);
    // A second, finer division inside each band.
    float fine = fbm(vec3(t * 23.0, uSeed * 1.3, 0.0));
    float ringlets = 0.55 + 0.45 * smoothstep(0.3, 0.6, fine);

    // GRAIN — along the angle as well as the radius, so the material is
    // particulate rather than striped. Sampled at a scale that is a few
    // pixels at the overview and a texture up close.
    float grain = noise(vec3(t * 160.0, angle * 24.0, uSeed));
    float speckle = 0.7 + 0.3 * grain;

    // Fade at both edges: a ring with a hard rim reads as a cut-out disc.
    float edge = smoothstep(0.0, 0.08, t) * (1.0 - smoothstep(0.9, 1.0, t));

    // SHADOW — the planet's, on the far side from the light.
    vec3 toCentre = vRingWorld - uCentre;
    vec3 L = normalize(uLight);
    float along = dot(toCentre, L);
    float across = length(toCentre - L * along);
    float shadow = (along < 0.0) ? smoothstep(uRadius * 0.9, uRadius * 1.3, across) : 1.0;
    // The lit face is the one the light is on; from behind, the plane is
    // dimmer but not dark — ring particles are translucent in aggregate.
    float faceLight = 0.55 + 0.45 * shadow;

    float density = annuli * ringlets * speckle * edge;
    float alpha = density * (0.28 + 0.5 * shadow);

    // Colour by band: the denser inner rings are the planet's own material,
    // the outer, sparser ones catch more of the accent.
    vec3 colour = mix(mix(uDeep, uCore, ringlets), uAccent, smoothstep(0.55, 0.95, t) * 0.4);
    gl_FragColor = vec4(colour * faceLight, alpha);
  }
`;

/**
 * The debris field — the ring's third dimension.
 *
 * A flat plane, however well textured, is a flat plane. A few hundred points
 * scattered through the same annuli with a little vertical spread, each catching
 * the light on its own, is what makes the eye read thickness. Point size falls
 * off with distance the way `Backdrop`'s twinkle field does, and the whole
 * field turns on the same slow carousel as the plane.
 */
export const DEBRIS_VERTEX = /* glsl */ `
  attribute float aSize;
  attribute float aBright;
  uniform float uPixelRatio;
  varying float vBright;
  void main() {
    vBright = aBright;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    // Small: these are grains, and 400 additive sprites at even a few pixels
    // each sum to a white bar across the ring. The first cut sized them like
    // the backdrop's stars and the ring vanished under its own debris.
    gl_PointSize = aSize * uPixelRatio * (18.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

export const DEBRIS_FRAGMENT = /* glsl */ `
  precision mediump float;
  uniform vec3 uColour;
  varying float vBright;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5) discard;
    float disc = smoothstep(0.5, 0.15, d);
    gl_FragColor = vec4(uColour, disc * vBright);
  }
`;
