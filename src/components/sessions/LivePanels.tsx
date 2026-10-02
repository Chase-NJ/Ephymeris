import { useMemo } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { UnitChart, type Mark, type Series } from "@/components/charts/UnitChart";
import {
  OUTCOME_ORDER,
  cumulativeOutcomes,
  holdPoints,
  inferHoldThreshold,
  rollingRightByOdor,
  type LiveTrials,
  type TrialOutcome,
} from "@/lib/sessions/liveTrials";

/**
 * The live per-animal panels (`ARCHITECTURE.md#live-session-views`).
 *
 * Three views of the one trial record, rebuilding what the lab's previous
 * software showed per animal — response probability, outcome composition, and
 * well-hold durations — inside this app's chart primitives so they inherit its
 * axis idiom and palette rather than becoming a second charting dialect.
 *
 * All three read `liveTrials`, so they can never disagree about what happened.
 */

/** Rolling window for the response curves, matching the profile default. */
const P_WINDOW = 20;

/** Series colours, from the analytics ramp (`DATA.md#colour-palette`). */
const ODOR_COLORS = ["#8B7EC8", "#CBA23E", "#52B79D", "#9E9FF6", "#BE7031", "#229582"];

const OUTCOME_STYLE: Record<TrialOutcome, { fill: string; label: string }> = {
  earned: { fill: "var(--color-ion)", label: "earned" },
  "hold-fail": { fill: "var(--color-status-warning)", label: "hold-fail" },
  "wrong-well": { fill: "var(--color-status-error)", label: "wrong well" },
  abstained: { fill: "var(--color-halo)", label: "abstained" },
};

export function LivePanels({
  live,
  strobeNames,
  chartHeight = 44,
}: {
  live: LiveTrials;
  strobeNames: Record<string, string>;
  /**
   * The `UnitChart` viewBox height. The SVGs stretch to their column, so this
   * is really an aspect ratio — a wide column passes a smaller number to keep
   * the three charts from towering (`StarPanel` passes 36).
   */
  chartHeight?: number;
}) {
  const trials = live.trials;

  if (trials.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-static">
        Panels populate as trials complete — response curves, outcome mix, and
        well-hold durations.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ResponsePanel live={live} strobeNames={strobeNames} height={chartHeight} />
      <OutcomePanel live={live} height={chartHeight} />
      <HoldPanel live={live} height={chartHeight} />
    </div>
  );
}

/** P(went right | odor), rolling, one curve per odor the task presented. */
function ResponsePanel({
  live,
  strobeNames,
  height,
}: {
  live: LiveTrials;
  strobeNames: Record<string, string>;
  height: number;
}) {
  const curves = useMemo(
    () =>
      live.odorCodes.map((code, index) => ({
        code,
        label: odorLabel(code, strobeNames),
        color: ODOR_COLORS[index % ODOR_COLORS.length]!,
        values: rollingRightByOdor(live.trials, code, P_WINDOW),
      })),
    [live.odorCodes, live.trials, strobeNames],
  );

  const longest = Math.max(1, ...curves.map((c) => c.values.length));
  const series: Series[] = curves
    .filter((c) => c.values.length > 1)
    .map((c) => ({
      stroke: c.color,
      strokeWidth: 1.5,
      segments: [
        {
          points: c.values.map((v, i) => ({
            x: longest === 1 ? 0 : i / (longest - 1),
            y: v,
          })),
        },
      ],
    }));

  return (
    <ChartFrame
      title="P(right | odor)"
      yTop="1"
      yBottom="0"
      xLeft="first"
      xRight={`${longest} expressed`}
      footer={
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
          {curves.map((c) => (
            <span key={c.code} className="flex items-center gap-1">
              <span
                className="inline-block h-[2px] w-3 rounded-full"
                style={{ backgroundColor: c.color }}
              />
              {c.label}
            </span>
          ))}
        </span>
      }
    >
      <UnitChart height={height} references={[{ y: 0.5 }]} series={series} />
    </ChartFrame>
  );
}

/** Cumulative outcome composition — the stacked bands. */
function OutcomePanel({ live, height }: { live: LiveTrials; height: number }) {
  const rows = useMemo(() => cumulativeOutcomes(live.trials), [live.trials]);

  // Stacked as cumulative upper edges, so each band's ribbon runs between the
  // running total below it and its own.
  const bands = useMemo(() => {
    if (rows.length < 2) return [];
    const denominator = rows.length - 1;
    let below = rows.map(() => 0);
    const out: Array<{ points: Array<{ x: number; low: number; high: number }>; fill: string; opacity: number }> = [];
    for (const outcome of OUTCOME_ORDER) {
      const above = rows.map((row, i) => below[i]! + row[outcome]);
      out.push({
        points: rows.map((_, i) => ({
          x: i / denominator,
          low: below[i]!,
          high: above[i]!,
        })),
        fill: OUTCOME_STYLE[outcome].fill,
        opacity: 0.7,
      });
      below = above;
    }
    return out;
  }, [rows]);

  return (
    <ChartFrame
      title="Outcome mix"
      yTop="1"
      yBottom="0"
      xLeft="trial 1"
      xRight={`${live.trials.length} completed`}
      footer={
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
          {OUTCOME_ORDER.map((outcome) => (
            <span key={outcome} className="flex items-center gap-1">
              <span
                className="inline-block size-1.5 rounded-[1px]"
                style={{ backgroundColor: OUTCOME_STYLE[outcome].fill, opacity: 0.85 }}
              />
              {OUTCOME_STYLE[outcome].label}
            </span>
          ))}
        </span>
      }
    >
      <UnitChart height={height} bands={bands} />
    </ChartFrame>
  );
}

/** Well-hold durations, filled where the hold was met and hollow where not. */
function HoldPanel({ live, height }: { live: LiveTrials; height: number }) {
  const points = useMemo(() => holdPoints(live.trials), [live.trials]);
  const threshold = useMemo(() => inferHoldThreshold(points), [points]);

  if (points.length === 0) {
    return (
      <ChartFrame title="Well hold">
        <p className="text-[11px] text-static">No well pokes recorded yet.</p>
      </ChartFrame>
    );
  }

  // Headroom above the longest hold so the topmost mark isn't clipped by the
  // frame, and so the threshold rule sits inside the plot rather than on it.
  const ceiling = Math.max(threshold ?? 0, ...points.map((p) => p.ms)) * 1.15 || 1;
  const lastIndex = Math.max(1, live.trials.length);

  const marks: Mark[] = points.map((p) => ({
    x: lastIndex === 1 ? 0 : (p.index - 1) / (lastIndex - 1),
    y: Math.min(1, p.ms / ceiling),
    r: 1.1,
    fill: p.side === "right" ? "var(--color-pulsar)" : "var(--color-ion)",
    hollow: !p.held,
    opacity: p.held ? 0.95 : 0.8,
  }));

  return (
    <ChartFrame
      title="Well hold"
      yTop={`${Math.round(ceiling)}ms`}
      yBottom="0"
      xLeft="trial 1"
      xRight={`${lastIndex}`}
      footer={
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
          <Legend fill="var(--color-pulsar)" label="right" />
          <Legend fill="var(--color-ion)" label="left" />
          <Legend fill="var(--color-static)" label="held" />
          <Legend fill="var(--color-static)" label="early" hollow />
        </span>
      }
    >
      <UnitChart
        height={height}
        references={threshold !== null ? [{ y: Math.min(1, threshold / ceiling) }] : []}
        marks={marks}
      />
    </ChartFrame>
  );
}

function Legend({
  fill,
  label,
  hollow = false,
}: {
  fill: string;
  label: string;
  hollow?: boolean;
}) {
  return (
    <span className="flex items-center gap-1">
      <span
        className="inline-block size-1.5 rounded-full"
        style={
          hollow
            ? { border: `1px solid ${fill}` }
            : { backgroundColor: fill }
        }
      />
      {label}
    </span>
  );
}

/**
 * `ODOR_3_ON` → `Odor 3`. The profile's own name is the source; only the
 * strobe-map suffix is trimmed, so a task that names its odors something more
 * descriptive keeps that name.
 */
function odorLabel(code: string, strobeNames: Record<string, string>): string {
  const raw = strobeNames[code];
  if (!raw) return `Strobe ${code}`;
  const match = /^ODOR_(\d+)_ON$/i.exec(raw);
  return match ? `Odor ${match[1]}` : raw;
}
