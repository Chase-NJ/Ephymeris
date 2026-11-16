/**
 * The live firing map's arithmetic (`RECORDING.md#live-firing-map`). Pure:
 * times are passed in, so it is tested without a clock.
 *
 * Each site carries two levels, read together:
 *
 *   - a FLASH, set to 1 by any spike and fading over `FLASH_TAU_MS`. This is
 *     what makes the map feel live: the eye sees each spike when it happens,
 *     not a rate that ramps up over the next second.
 *   - a RATE, an exponentially weighted spike rate (`RATE_TAU_MS`), drawn on
 *     a FIXED log scale. Fixed, because a scale relative to the busiest site
 *     re-shades every other site whenever the loudest one changes.
 */

export const FLASH_TAU_MS = 120;
export const RATE_TAU_MS = 2000;
/** The rate scale's ends: at or below the floor a site reads quiet, at or above the ceiling full. */
export const RATE_FLOOR_HZ = 0.5;
export const RATE_CEIL_HZ = 100;
/** The steady glow never reaches a flash's brightness, so a spike always shows. */
export const RATE_MAX_STRENGTH = 0.7;

/** 0…1 on the fixed log scale. */
export function rateStrength(hz: number): number {
  if (!(hz > RATE_FLOOR_HZ)) return 0;
  const s = Math.log(hz / RATE_FLOOR_HZ) / Math.log(RATE_CEIL_HZ / RATE_FLOOR_HZ);
  return Math.min(1, s);
}

export class FiringModel {
  readonly channels: readonly string[];
  private readonly index = new Map<string, number>();
  private readonly flash: Float64Array;
  /** In Hz: each spike adds 1/τ, and the whole decays with τ, so a steady λ settles at λ. */
  private readonly rate: Float64Array;
  private last: number | null = null;

  constructor(channels: readonly string[]) {
    this.channels = channels;
    channels.forEach((c, i) => this.index.set(c, i));
    this.flash = new Float64Array(channels.length);
    this.rate = new Float64Array(channels.length);
  }

  /** One `intan.spikes` batch. Channels not on this map are ignored. */
  add(counts: Record<string, number>, now: number): void {
    this.advance(now);
    for (const channel in counts) {
      const i = this.index.get(channel);
      const n = counts[channel] ?? 0;
      if (i === undefined || n <= 0) continue;
      this.flash[i] = 1;
      this.rate[i] = (this.rate[i] ?? 0) + (n * 1000) / RATE_TAU_MS;
    }
  }

  /** Decay both levels to `now`. Idempotent for a repeated `now`. */
  advance(now: number): void {
    const dt = this.last === null ? 0 : now - this.last;
    this.last = now;
    if (dt <= 0) return;
    const f = Math.exp(-dt / FLASH_TAU_MS);
    const r = Math.exp(-dt / RATE_TAU_MS);
    for (let i = 0; i < this.flash.length; i++) {
      this.flash[i] = (this.flash[i] ?? 0) * f;
      this.rate[i] = (this.rate[i] ?? 0) * r;
    }
  }

  /** 0…1: how brightly site `i` is drawn. */
  strength(i: number): number {
    return Math.max(this.flash[i] ?? 0, RATE_MAX_STRENGTH * rateStrength(this.rate[i] ?? 0));
  }

  rateHz(i: number): number {
    return this.rate[i] ?? 0;
  }
}

/** The p-th quantile (0…1) of a sample, or null when it is empty. */
export function quantile(values: readonly number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] ?? null;
}
