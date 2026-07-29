/**
 * The house chart primitive — a 0–1 × 0–1 domain in unit space.
 *
 * Generalises the idiom the metric sparklines established: `viewBox="0 0 100 H"`
 * with `preserveAspectRatio="none"` so the chart stretches to its container
 * without measuring it, `vectorEffect="non-scaling-stroke"` so that stretch
 * never distorts line weight, and y flipped manually as `(1 - v) * H`.
 *
 * **No text goes inside this SVG.** `preserveAspectRatio="none"` scales
 * non-uniformly, which is fine for strokes and ruinous for glyphs — labels
 * belong in the HTML beside it, which is what `ChartFrame` is for.
 *
 * Layers that subscribe to shared state — the per-animal highlight above all —
 * render as `children` inside the SVG rather than as `series` props, so a
 * hover re-renders one small layer and never the chart that contains it.
 * `unitX`/`unitY`/`ribbon` are exported for exactly those layers.
 */

import type { ReactNode } from "react";

export interface Point {
  x: number;
  y: number;
}

export interface BandPoint {
  x: number;
  low: number;
  high: number;
}

export interface Segment {
  points: Point[];
  /** Drawn dashed to mark a discontinuity rather than interpolating it. */
  dashed?: boolean;
}

export interface Series {
  segments: Segment[];
  stroke: string;
  strokeWidth?: number;
  opacity?: number;
}

export interface Mark {
  x: number;
  y: number;
  r: number;
  fill: string;
  /** Hollow marks carry a low-confidence value — present, but not to be read
   *  as firmly as a filled one. */
  hollow?: boolean;
  opacity?: number;
}

export interface Reference {
  /** A horizontal rule at this y, or an explicit two-point line. */
  y?: number;
  from?: Point;
  to?: Point;
}

/** x in 0–1 → viewBox units. */
export function unitX(x: number): string {
  return (x * 100).toFixed(2);
}

/** y in 0–1 → viewBox units, flipped so 1.0 is the top. */
export function unitY(y: number, height: number): string {
  return ((1 - y) * height).toFixed(2);
}

export function UnitChart({
  height = 46,
  references = [],
  bands = [],
  series = [],
  marks = [],
  className,
  children,
}: {
  height?: number;
  references?: Reference[];
  bands?: Array<{ points: BandPoint[]; fill: string; opacity?: number }>;
  series?: Series[];
  marks?: Mark[];
  className?: string;
  /** Extra layers drawn between the series and the marks — see the header. */
  children?: ReactNode;
}) {
  const X = unitX;
  const Y = (y: number) => unitY(y, height);

  return (
    <svg
      viewBox={`0 0 100 ${height}`}
      className={className ?? "w-full"}
      preserveAspectRatio="none"
      aria-hidden
    >
      {references.map((reference, index) => {
        const from = reference.from ?? { x: 0, y: reference.y ?? 0.5 };
        const to = reference.to ?? { x: 1, y: reference.y ?? 0.5 };
        return (
          <line
            key={`ref-${index}`}
            x1={X(from.x)}
            y1={Y(from.y)}
            x2={X(to.x)}
            y2={Y(to.y)}
            stroke="var(--color-halo)"
            strokeWidth={0.5}
            strokeDasharray="2 2"
            opacity={0.35}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}

      {/* Bands before lines: SVG paints in document order and has no z-index,
          so this is what puts a confidence ribbon behind its own curve. */}
      {bands.map((band, index) =>
        band.points.length < 2 ? null : (
          <polygon
            key={`band-${index}`}
            points={ribbon(band.points, height)}
            fill={band.fill}
            fillOpacity={band.opacity ?? 0.12}
            stroke="none"
          />
        ),
      )}

      {series.map((line, lineIndex) =>
        line.segments.map((segment, index) =>
          segment.points.length < 2 ? null : (
            <polyline
              key={`line-${lineIndex}-${index}`}
              points={segment.points.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ")}
              fill="none"
              stroke={line.stroke}
              strokeWidth={line.strokeWidth ?? 1.5}
              strokeLinejoin="round"
              strokeDasharray={segment.dashed ? "2 2" : undefined}
              opacity={line.opacity ?? 1}
              vectorEffect="non-scaling-stroke"
            />
          ),
        ),
      )}

      {children}

      {marks.map((mark, index) => (
        <circle
          key={`mark-${index}`}
          cx={X(mark.x)}
          cy={Y(mark.y)}
          r={mark.r}
          fill={mark.hollow ? "none" : mark.fill}
          stroke={mark.hollow ? mark.fill : "none"}
          strokeWidth={mark.hollow ? 1 : 0}
          opacity={mark.opacity ?? 1}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

/** Forward along the low edge, back along the high edge, closing the ribbon. */
export function ribbon(points: BandPoint[], height: number): string {
  const low = points.map((p) => `${unitX(p.x)},${unitY(p.low, height)}`);
  const high = [...points].reverse().map((p) => `${unitX(p.x)},${unitY(p.high, height)}`);
  return [...low, ...high].join(" ");
}

/**
 * Split a value list into solid runs, marking a dashed bridge wherever a gap
 * was skipped — so a session that scored nothing shows as a discontinuity
 * rather than a line interpolated through nothing (`analytics.md` §3.6).
 */
export interface Edge {
  from: Point;
  to: Point;
  /** Bridges a gap — drawn dashed, exactly as `segmentsWithGaps` would. */
  dashed: boolean;
  /** Where `to` sat in the original list. The ordinal, not the edge count, so
   *  a delay computed from it tracks the session a node belongs to even when
   *  earlier ones are missing. */
  index: number;
}

/**
 * The same split as `segmentsWithGaps`, but one edge at a time.
 *
 * A polyline is the right shape for drawing a trail and the wrong one for
 * *walking* it: revealing a trail node by node needs each hop to be its own
 * element with its own delay. Same gap rules, so the two cannot disagree about
 * where a discontinuity is.
 */
export function edgesWithGaps(points: Array<Point | null>): Edge[] {
  const edges: Edge[] = [];
  let previous: Point | null = null;
  let gapPending = false;

  points.forEach((point, index) => {
    if (point === null) {
      if (previous !== null) gapPending = true;
      return;
    }
    if (previous !== null) {
      edges.push({ from: previous, to: point, dashed: gapPending, index });
    }
    gapPending = false;
    previous = point;
  });
  return edges;
}

export function segmentsWithGaps(points: Array<Point | null>): Segment[] {
  const segments: Segment[] = [];
  let current: Point[] = [];
  let lastReal: Point | null = null;
  let gapPending = false;

  for (const point of points) {
    if (point === null) {
      if (current.length > 0) {
        segments.push({ points: current });
        lastReal = current[current.length - 1]!;
        current = [];
      }
      gapPending = true;
      continue;
    }
    if (gapPending && lastReal) {
      segments.push({ points: [lastReal, point], dashed: true });
      gapPending = false;
    }
    current.push(point);
  }
  if (current.length > 0) segments.push({ points: current });
  return segments;
}
