/**
 * The arithmetic behind the four recording windows.
 *
 * Pure on purpose (`README.md#tests`: Vitest covers `src/lib/**` only): every
 * function here can be wrong in a way that still draws a confident picture — a
 * spike a third of a millisecond off its crossing, a probe drawn upside down, a
 * histogram whose tallest bar is not its largest count — and none of that
 * throws. So it lives where it can be pinned without a canvas.
 */

import type { ProbePage } from "./types";

/**
 * Crop a snippet cut at the sidecar's fixed window down to a SpikeScope time
 * scale. RHX places the threshold crossing one third of the way across, and so
 * does this; `zeroIndex` is where that crossing sits in the returned samples.
 */
export function cropSnippet(
  microvolts: readonly number[],
  sampleRate: number,
  cutPreMs: number,
  timeScaleMs: number,
): { values: number[]; zeroIndex: number } {
  const perMs = sampleRate / 1000;
  const center = Math.round(cutPreMs * perMs);
  const before = Math.min(center, Math.round((timeScaleMs / 3) * perMs));
  const after = Math.min(
    microvolts.length - 1 - center,
    Math.round(((2 * timeScaleMs) / 3) * perMs),
  );
  return { values: microvolts.slice(center - before, center + after + 1), zeroIndex: before };
}

/**
 * Vertical position of a voltage, in pixels from the top.
 *
 * `scaleUv` is the FULL height of the display, as in RHX ("how many microVolts
 * the full vertical length represents"), so ±scale/2 are the edges and zero is
 * the middle. Positive is up — the convention every spike display uses, and the
 * opposite of a canvas.
 */
export function voltageToY(microvolts: number, scaleUv: number, height: number): number {
  return height / 2 - (microvolts / scaleUv) * height;
}

/** The inverse, for dragging the threshold line. Rounded: RHX takes integers. */
export function yToVoltage(y: number, scaleUv: number, height: number): number {
  return Math.round(((height / 2 - y) / height) * scaleUv);
}

/**
 * Bar heights in 0…1. With `log`, by log10(count + 1): a bin holding one
 * interval stays visible beside one holding a thousand, and an empty bin is
 * still exactly zero — which plain log10 cannot give.
 */
export function barHeights(counts: readonly number[], log = false): number[] {
  const scale = (n: number) => (log ? Math.log10(n + 1) : n);
  const max = counts.reduce((m, c) => Math.max(m, scale(c)), 0);
  return max === 0 ? counts.map(() => 0) : counts.map((c) => scale(c) / max);
}

/**
 * Where each bin's bar sits, in px from the left, when `count` bins of
 * `binMs` cover `spanMs`. The last bin may be PARTIAL — 50 ms at 20 ms bins is
 * three bins, the third 10 ms wide — and is drawn at its true width rather
 * than stretched to a full one, which would show a count over 10 ms as if it
 * were over 20. A one-pixel gutter separates bars; a bar is never under 1 px.
 */
export function binRects(
  count: number,
  binMs: number,
  spanMs: number,
  width: number,
): { x: number; w: number }[] {
  if (count <= 0 || !(spanMs > 0) || !(binMs > 0)) return [];
  const perMs = width / spanMs;
  const out: { x: number; w: number }[] = [];
  for (let i = 0; i < count; i += 1) {
    const x = i * binMs * perMs;
    const end = Math.min(width, (i + 1) * binMs * perMs);
    out.push({ x, w: Math.max(1, end - x - 1) });
  }
  return out;
}

/** A round axis ceiling at or above `value`: 1, 2, 5 × a power of ten. */
export function niceCeiling(value: number): number {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const lead = value / power;
  const step = lead <= 1 ? 1 : lead <= 2 ? 2 : lead <= 5 ? 5 : 10;
  return step * power;
}

export interface ProbeFit {
  /** Pixels per map unit — the same on both axes, so sites stay round. */
  scale: number;
  toX: (x: number) => number;
  toY: (y: number) => number;
}

/**
 * Fit a probe-map page into a box, keeping its aspect ratio and FLIPPING Y.
 *
 * Intan's probe maps are drawn y-up (a shank's tip is its smallest y and sits
 * at the bottom of RHX's display); a canvas is y-down. Skip the flip and the
 * probe is drawn tip-up, every site on the right channel and in the wrong
 * place — depth is the one thing the map is for.
 */
export function fitProbeMap(page: ProbePage, width: number, height: number, pad = 16): ProbeFit {
  const xs: number[] = [];
  const ys: number[] = [];
  for (const line of page.lines) {
    xs.push(line.x1, line.x2);
    ys.push(line.y1, line.y2);
  }
  for (const text of page.texts) {
    xs.push(text.x);
    ys.push(text.y);
  }
  for (const port of page.ports) {
    for (const site of port.sites) {
      xs.push(site.x - site.width / 2, site.x + site.width / 2);
      ys.push(site.y - site.height / 2, site.y + site.height / 2);
    }
  }
  if (xs.length === 0) return { scale: 1, toX: (x) => x, toY: (y) => y };

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanY = Math.max(maxY - minY, 1e-6);
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanY * scale) / 2;
  return {
    scale,
    toX: (x) => offsetX + (x - minX) * scale,
    toY: (y) => offsetY + (maxY - y) * scale,
  };
}

/** 0…1 fill strength for a site, against the busiest site on the map. */
export function rateStrength(rate: number, maxRate: number): number {
  if (!(rate > 0) || !(maxRate > 0)) return 0;
  // Square root: firing rates are heavy-tailed, and a linear ramp leaves every
  // site but the loudest looking silent.
  return Math.min(1, Math.sqrt(rate / maxRate));
}

/** "A-016" → 16. Used to order channel pickers the way RHX does. */
export function channelNumber(name: string): number {
  const n = Number(name.split("-")[1]);
  return Number.isFinite(n) ? n : 0;
}

/** Native channel names for a port and an inclusive range. */
export function channelRange(port: string, first: number, last: number): string[] {
  const out: string[] = [];
  for (let n = first; n <= last; n += 1) out.push(`${port.toUpperCase()}-${String(n).padStart(3, "0")}`);
  return out;
}
