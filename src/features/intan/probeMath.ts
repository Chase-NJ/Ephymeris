/**
 * Probe geometry and channel naming, shared by the Record step's preview and
 * the live firing map.
 *
 * Pure on purpose (`DEVELOPING.md#tests`: Vitest covers pure modules only): a
 * probe drawn upside down still draws a confident picture and throws nothing,
 * so it lives where it can be pinned without a renderer.
 */

import type { ProbePage } from "./types";

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

/** Native channel names for a port and an inclusive range. */
export function channelRange(port: string, first: number, last: number): string[] {
  const out: string[] = [];
  for (let n = first; n <= last; n += 1) out.push(`${port.toUpperCase()}-${String(n).padStart(3, "0")}`);
  return out;
}
