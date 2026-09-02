/**
 * A cohort's world — `cohorts.md` §5.
 *
 * Everything here fails QUIETLY without a check, which is why it is pure and
 * why this file exists. A drifted seed does not throw: it silently gives every
 * untouched cohort in the lab a different planet than the one its operators
 * learned, and the only symptom is that the room no longer recognises its own
 * library. A resolution bug does not throw either — it just renders somebody's
 * chosen world as the derived one.
 */

import { describe, expect, it } from "vitest";

import {
  PLANET_TYPES,
  derivedAppearance,
  livelinessFor,
  planetPalette,
  radiusFor,
  rerollSeed,
  resolveAppearance,
  typeIndex,
} from "./appearance";

const ID = "9f2c7c4e-0000-4000-8000-000000000001";

describe("derived worlds", () => {
  it("gives the same cohort the same world forever", () => {
    // The whole contract `prng.ts` states: identical output for identical
    // input, between renders, sessions and machines.
    expect(derivedAppearance(ID)).toEqual(derivedAppearance(ID));
  });

  it("is pinned, so a reordered generator cannot drift in silence", () => {
    /*
     * The one test that would catch someone adding a `rand()` call in the
     * middle of `derivedAppearance` rather than at the end. Every value below
     * is an observation of the current generator, not a preference — if this
     * fails, the question is whether the drift was intended, because it
     * re-rolls every untouched cohort in every lab at once.
     */
    const world = derivedAppearance(ID);
    expect(world.type).toBe("ice");
    expect(world.hue).toBeCloseTo(57.085072, 4);
    expect(world.ring).toBe(false);
    expect(world.seed).toBe(78458);
    // A second id must not land on the same world by construction.
    expect(derivedAppearance("a-different-cohort")).not.toEqual(world);
  });

  it("gives every cohort a drawable type", () => {
    for (let i = 0; i < 200; i += 1) {
      const world = derivedAppearance(`cohort-${i}`);
      expect(PLANET_TYPES).toContain(world.type);
      expect(world.hue).toBeGreaterThanOrEqual(0);
      expect(world.hue).toBeLessThan(360);
      expect(typeIndex(world.type)).toBeGreaterThanOrEqual(0);
    }
  });

  it("does not put a ring on most of them", () => {
    // A ring is a distinguishing mark, and a mark most things carry stops
    // distinguishing anything.
    const ringed = Array.from({ length: 300 }, (_, i) =>
      derivedAppearance(`cohort-${i}`),
    ).filter((w) => w.ring).length;
    expect(ringed).toBeLessThan(150);
  });
});

describe("resolution", () => {
  it("falls back to the derived world when nothing is stored", () => {
    expect(resolveAppearance(ID, null)).toEqual(derivedAppearance(ID));
    expect(resolveAppearance(ID, undefined)).toEqual(derivedAppearance(ID));
  });

  it("lets a stored world win", () => {
    const stored = { type: "gas", hue: 41, ring: true, seed: 7734 };
    expect(resolveAppearance(ID, stored)).toEqual({
      type: "gas",
      hue: 41,
      ring: true,
      seed: 7734,
    });
  });

  it("fills a half-written record field by field, not wholesale", () => {
    /*
     * A record from an older build, or one a hand-edit damaged. Falling back
     * wholesale would throw away the three fields that ARE readable — and the
     * operator would watch their tuned world revert because one key was wrong.
     */
    const derived = derivedAppearance(ID);
    const resolved = resolveAppearance(ID, {
      type: "not-a-world",
      hue: 200,
      ring: true,
      seed: 5,
    } as never);
    expect(resolved.type).toBe(derived.type); // the unreadable one falls back
    expect(resolved.hue).toBe(200); // the readable ones do not
    expect(resolved.ring).toBe(true);
    expect(resolved.seed).toBe(5);
  });

  it("wraps a hue that arrived outside the circle", () => {
    expect(resolveAppearance(ID, { type: "ice", hue: 420, ring: false, seed: 1 }).hue).toBe(60);
    expect(resolveAppearance(ID, { type: "ice", hue: -30, ring: false, seed: 1 }).hue).toBe(330);
  });

  it("ignores a non-finite number rather than rendering NaN", () => {
    const derived = derivedAppearance(ID);
    const resolved = resolveAppearance(ID, {
      type: "lava",
      hue: Number.NaN,
      ring: false,
      seed: Number.POSITIVE_INFINITY,
    });
    expect(resolved.hue).toBe(derived.hue);
    expect(resolved.seed).toBe(derived.seed);
  });
});

describe("re-roll", () => {
  it("changes the weather and nothing else", () => {
    // The split the panel promises in words: a re-roll must never cost the
    // operator the identity they already recognise across the room.
    const before = resolveAppearance(ID, { type: "gas", hue: 41, ring: true, seed: 1 });
    const after = rerollSeed(before);
    expect(after.type).toBe(before.type);
    expect(after.hue).toBe(before.hue);
    expect(after.ring).toBe(before.ring);
  });
});

describe("the palette", () => {
  it("keeps a type recognisable at every hue", () => {
    /*
     * Saturation and lightness belong to the TYPE, not the hue — which is what
     * stops one slider turning an ice world into a lava one, and what keeps
     * these inside the app's matte register instead of drifting toward
     * saturated primaries.
     */
    for (const hue of [0, 90, 180, 270]) {
      const ice = planetPalette({ type: "ice", hue, ring: false, seed: 0 });
      const lava = planetPalette({ type: "lava", hue, ring: false, seed: 0 });
      const iceHsl = { h: 0, s: 0, l: 0 };
      const lavaHsl = { h: 0, s: 0, l: 0 };
      ice.core.getHSL(iceHsl);
      lava.core.getHSL(lavaHsl);
      // Ice is always the paler of the two, whatever hue either is wearing.
      expect(iceHsl.l).toBeGreaterThan(lavaHsl.l);
    }
  });

  it("gives every declared type a full palette", () => {
    for (const type of PLANET_TYPES) {
      const palette = planetPalette({ type, hue: 120, ring: false, seed: 0 });
      for (const colour of [
        palette.deep,
        palette.edge,
        palette.core,
        palette.peak,
        palette.accent,
        palette.mineral,
        palette.atmosphere,
      ]) {
        expect(Number.isFinite(colour.r)).toBe(true);
        expect(Number.isFinite(colour.g)).toBe(true);
        expect(Number.isFinite(colour.b)).toBe(true);
      }
    }
  });
});

describe("the readings a planet carries", () => {
  it("grows a world with its roster, within bounds", () => {
    expect(radiusFor(24)).toBeGreaterThan(radiusFor(1));
    // Bounded hard: the radius drives the hit sphere (×4), the reticle, the
    // nameplate drop and the orbit reach, so an unbounded one would let a big
    // cohort swallow its neighbours' click targets.
    expect(radiusFor(10_000)).toBeLessThanOrEqual(radiusFor(24));
    expect(radiusFor(0)).toBeGreaterThan(0);
  });

  it("reads a recent edit as alive and an old one as quiet", () => {
    const today = new Date().toISOString();
    const longAgo = new Date(Date.now() - 90 * 86_400_000).toISOString();
    expect(livelinessFor(today)).toBeGreaterThan(livelinessFor(longAgo));
  });

  it("never returns zero, because a frozen world reads as a fault", () => {
    for (const value of [null, undefined, "", "not-a-date", "1999-01-01T00:00:00Z"]) {
      expect(livelinessFor(value)).toBeGreaterThan(0);
      expect(livelinessFor(value)).toBeLessThanOrEqual(1);
    }
  });
});
