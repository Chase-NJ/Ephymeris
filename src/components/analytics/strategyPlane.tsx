import type { ReactNode } from "react";

import type { StrategyAxes } from "@/lib/analytics/view";

/**
 * The plane both strategy panels draw in (`DATA.md#strategy-plane`).
 *
 * Two panels occupy it — one point per *session* across a cohort, one point
 * per *trial* within a single session — and they must agree on
 * every reference mark, or the same position would mean two things depending
 * on the selector. So the axes, the bias diagonal, the chance mark, the region
 * captions and the prose note all live here and neither panel owns them.
 *
 * Both axes are "fraction correct at this well": x and y are the two sides
 * `strategyAxes` found, each pooling every condition answered there
 * (`DATA.md#strategy-plane`). Nothing here knows what an odor or a well is —
 * the captions are built from the axes' own labels.
 */

export const SIZE = 100;

/**
 * Breathing room around the unit square, in viewBox units.
 *
 * A session scoring 0.0 or 1.0 puts its marker *on* the square's edge, and a
 * `0 0 SIZE SIZE` viewBox sliced those markers to half-circles — data at the
 * extremes is exactly the data that must not look broken. Widening the window
 * rather than remapping the coordinates keeps the `px`/`py` contract intact:
 * both panels' geometry is untouched, they just render with a margin.
 */
export const PAD = 4;

/** The viewBox both panels must use — the unit square plus the margin. */
export const PLANE_VIEWBOX = `${-PAD} ${-PAD} ${SIZE + 2 * PAD} ${SIZE + 2 * PAD}`;

/** Unit space → viewBox. y inverts: 1.0 is the top of the plot, not the bottom. */
export const px = (x: number) => (x * SIZE).toFixed(2);
export const py = (y: number) => ((1 - y) * SIZE).toFixed(2);

/**
 * The reference marks, drawn under everything a panel puts on top.
 *
 * The anti-diagonal is the load-bearing one: an animal giving the same response
 * regardless of stimulus scores `x + y = 1` whatever its side preference, so
 * that line is *every* pure bias, and distance from it is discrimination
 * strength. The captions sit just inside the corners they describe, at an
 * opacity that keeps them legible without competing with the data.
 */
export function PlaneReferences() {
  return (
    <g aria-hidden>
      {/* Every pure side bias lies on this line. */}
      <line
        x1={0}
        y1={0}
        x2={SIZE}
        y2={SIZE}
        stroke="var(--color-halo)"
        strokeWidth={0.5}
        strokeDasharray="2 2"
        opacity={0.35}
        vectorEffect="non-scaling-stroke"
      />
      {/* Chance on both conditions. */}
      <circle cx={SIZE / 2} cy={SIZE / 2} r={1} fill="var(--color-halo)" opacity={0.6} />

      <Caption x={SIZE - 3} y={5} anchor="end">
        discriminating
      </Caption>
      <Caption x={SIZE / 2} y={SIZE / 2 - 3} anchor="middle">
        chance
      </Caption>
      <Caption x={3} y={SIZE - 3} anchor="start">
        reversed
      </Caption>
      {/* Placed on the bias line itself rather than in a free corner, so it
          labels the line and not the quadrant it happens to sit in. No arrow:
          the line runs up-and-left from here, and the obvious ↗ would point
          along the one direction it does not go. */}
      <Caption x={SIZE - 3} y={SIZE - 3} anchor="end">
        side bias
      </Caption>
    </g>
  );
}

/**
 * A caption inside the plot.
 *
 * Safe only because both panels use `preserveAspectRatio="xMidYMid meet"` —
 * text inside a `none` viewBox gets stretched non-uniformly, which is why
 * `ChartFrame` keeps its axis labels in HTML instead.
 *
 * Knocked out of the background with a Void stroke under the fill: the corners
 * these label are exactly where the data piles up — "discriminating" sits where
 * every well-trained animal ends — so a plain dim label is unreadable in the one
 * plot where it matters most. `paintOrder` puts the stroke behind the glyphs,
 * so the outline thickens the halo rather than eating the letterforms.
 */
function Caption({
  x,
  y,
  anchor,
  children,
}: {
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
  children: ReactNode;
}) {
  return (
    <text
      x={x}
      y={y}
      textAnchor={anchor}
      fill="var(--color-static)"
      stroke="var(--color-void)"
      strokeWidth={1}
      strokeLinejoin="round"
      paintOrder="stroke"
      opacity={0.7}
      fontSize={3.4}
      className="font-mono"
    >
      {children}
    </text>
  );
}

/**
 * What each region of the plane actually means, in the task's own vocabulary.
 *
 * The in-plot captions are three words each and can only name the corners; this
 * is the reading. Written from the profile's metric labels rather than from any
 * knowledge of the task, so for GRGL it names odor 1 and odor 3 by the names
 * the sketch itself declared, and for anything else it is still correct.
 */
export function StrategyNote({ axes }: { axes: StrategyAxes }) {
  // No border or text sizing of its own: it renders inside `HowToRead`,
  // which owns the disclosure chrome and the prose style.
  return (
    <div>
      {/* The axis→metric mapping is already in the frame's footer directly
          above, so this opens with what a position *means* instead. */}
      <p>
        Each axis is the fraction correct at one answer, pooled over every
        condition answered there — so a task presenting four odors reads on the
        same two axes a two-odor task does.
      </p>
      <ul className="mt-1 flex flex-col gap-0.5">
        <Region label="top-right">
          correct on both — discriminating the stimulus.
        </Region>
        <Region label="centre">chance on both — no evidence of either.</Region>
        <Region label="diagonal">
          high on one and low on the other:{" "}
          <em className="text-static not-italic">the same response whatever the stimulus</em> —
          a side bias, not a skill. Toward the top-left it is all{" "}
          <span className="font-mono">{axes.y.side}</span>; toward the
          bottom-right, all <span className="font-mono">{axes.x.side}</span>.
        </Region>
        <Region label="bottom-left">
          wrong on both — the reversed contingency. Still learning, inverted.
        </Region>
      </ul>
      <p className="mt-1">
        Distance from the diagonal is discrimination strength; position along it
        is which side is favoured.
      </p>
    </div>
  );
}

function Region({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li className="flex gap-1.5">
      <span className="shrink-0 font-mono text-static">{label}</span>
      <span>{children}</span>
    </li>
  );
}

/** The surface both panels sit on, so they swap without the frame moving. */
export function StrategyPanel({ children }: { children: ReactNode }) {
  return <div className="telemetry p-4">{children}</div>;
}

/**
 * The shared "this profile has no plane" state.
 *
 * Names the profile and its metric count rather than rendering an empty frame
 * (`DATA.md#strategy-plane`): "this task declares three conditions" is
 * actionable, an empty box is not.
 */
export function NoPlane({
  hasRuns,
  reason = null,
}: {
  hasRuns: boolean;
  /**
   * Why this cohort's profiles cannot be plotted, when something ran.
   *
   * Named rather than left as a generic absence: "no plane" reads as a broken
   * panel, and the operator can act on "every condition is answered at the same
   * place" — it means the task is a shaping task, not that the archive is
   * damaged.
   */
  reason?: string | null;
}) {
  return (
    <StrategyPanel>
      <p className="text-[12px] leading-relaxed text-static">
        {!hasRuns
          ? "No scored runs yet, so there is no strategy to plot."
          : reason
            ? `Nothing here can go on the plane — ${reason}. The plane needs two opposing answers, one per axis.`
            : "Nothing here can go on the plane: it needs two opposing answers, one per axis, and no task in this cohort has them."}
      </p>
    </StrategyPanel>
  );
}
