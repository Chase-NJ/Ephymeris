/**
 * The parameter dial's geometry (`TASKS.md#parameter-dial`). Pure: no React.
 *
 * The dial is the upper half of a tilted orbit — an ellipse seen from slightly
 * above, the way an orrery's plane reads — with a fixed ZENITH at the top. The
 * categories are planets on it, one stop apart; selecting one turns the whole
 * orbit until that planet sits at the zenith. Everything here is a function of
 * one number, `phase` — the (fractional) index at the zenith — so a spring on
 * phase moves every planet ALONG the arc rather than in straight lines.
 */

export interface OrbitGeometry {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

/** Degrees between neighbouring stops: as wide as 40°, but never so wide that
 *  the end planets pass below the horizon when the other end is selected. */
export function stopSpacing(n: number): number {
  return n <= 1 ? 0 : Math.min(40, 90 / (n - 1));
}

/** Where a stop sits, in degrees: 90 is the zenith, 180 the left horizon. */
export function angleOf(index: number, phase: number, n: number): number {
  return 90 + (phase - index) * stopSpacing(n);
}

export interface PlanetPlacement {
  x: number;
  y: number;
  /** 0 at the horizon, 1 at the zenith — drives size and label opacity. */
  height: number;
}

export function planetAt(
  index: number,
  phase: number,
  n: number,
  orbit: OrbitGeometry,
): PlanetPlacement {
  const theta = (angleOf(index, phase, n) * Math.PI) / 180;
  return {
    x: orbit.cx + orbit.rx * Math.cos(theta),
    y: orbit.cy - orbit.ry * Math.sin(theta),
    height: Math.max(0, Math.sin(theta)),
  };
}

/** A point on the orbit at an angle in degrees — for the reticle ticks. */
export function orbitPoint(degrees: number, orbit: OrbitGeometry): { x: number; y: number } {
  const theta = (degrees * Math.PI) / 180;
  return { x: orbit.cx + orbit.rx * Math.cos(theta), y: orbit.cy - orbit.ry * Math.sin(theta) };
}

/** The drawn half of the orbit, left horizon to right, over the top. */
export function upperArc(orbit: OrbitGeometry): string {
  const { cx, cy, rx, ry } = orbit;
  return `M ${cx - rx} ${cy} A ${rx} ${ry} 0 0 1 ${cx + rx} ${cy}`;
}

/** Wheel deltas this far apart are one stop. */
export const WHEEL_STEP = 50;

/**
 * Fold one wheel event into the running total; returns the stops to move and
 * what remains. A trackpad sends dozens of small deltas per flick, a mouse a
 * few large ones — accumulating to a threshold makes both one stop per gesture.
 */
export function accumulateWheel(
  pending: number,
  delta: number,
  step: number = WHEEL_STEP,
): { stops: number; pending: number } {
  const total = pending + delta;
  const stops = Math.trunc(total / step);
  return { stops, pending: stops === 0 ? total : 0 };
}
