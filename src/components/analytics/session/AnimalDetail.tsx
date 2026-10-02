import { motion } from "framer-motion";
import { useState } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { Segmented } from "@/components/common/controls";
import { outcomeParts } from "@/lib/analytics/session";
import type {
  ConditionOutcomes,
  RunSeries,
  RunSummary,
  TrialRecord,
} from "@/lib/analytics/types";
import { OUTCOME_STYLE, colorForIndex, type OutcomeKey } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";

/**
 * The inside of one animal's run (`DATA.md#pooling-across-tasks`) — the views a
 * card-sized tile cannot carry, behind one segmented selector so only one is on
 * screen at a time.
 *
 * The tape is the reason the per-trial wire field exists
 * (`DATA.md#per-trial-tape`): streaks, side-bias episodes and the moment an
 * animal stopped working are invisible in any aggregate. The other three are
 * the card's own numbers at full size — the trajectory the sparkline
 * compresses, the per-odor composition, and the engagement ladder as a funnel.
 */
export function AnimalDetail({
  run,
  series,
  color,
  revealKey,
}: {
  run: RunSummary;
  series: RunSeries | null;
  color: string;
  revealKey: string;
}) {
  const [view, setView] = useState<DetailView>("tape");

  return (
    <motion.div
      className="border-t border-halo px-3 py-2.5"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={springSnappy}
    >
      <div className="flex items-center justify-between gap-2">
        <Segmented
          value={view}
          onChange={setView}
          label="Detail view"
          options={[
            { value: "tape", label: "Tape" },
            { value: "trajectory", label: "Trajectory" },
            { value: "odors", label: "By odor" },
            { value: "engagement", label: "Engagement" },
          ]}
        />
      </div>

      <div className="mt-2.5">
        {view === "tape" && <TapeView run={run} series={series} />}
        {view === "trajectory" && <TrajectoryView series={series} />}
        {view === "odors" && <OdorView run={run} />}
        {view === "engagement" && (
          <EngagementView run={run} color={color} revealKey={revealKey} />
        )}
      </div>
    </motion.div>
  );
}

type DetailView = "tape" | "trajectory" | "odors" | "engagement";

/** Wire spelling → the shared outcome palette; aborted drawn by shape below. */
const TAPE_KEY: Record<string, OutcomeKey | null> = {
  rewarded: "rewarded",
  "hold-failed": "holdFailed",
  "wrong-well": "wrongWell",
  "no-response": "noResponse",
  aborted: null,
};

/**
 * Every trial in stream order, one lane per condition, coloured by how it
 * resolved. The lanes share one x axis — the run's own trial order — so the
 * interleaving is visible: a side-bias episode reads as one lane going red
 * while the other stays green *at the same time*.
 *
 * Aborted trials (never administered) are drawn at half height rather than a
 * fifth colour: they read as "didn't get far", which is what they are.
 */
function TapeView({ run, series }: { run: RunSummary; series: RunSeries | null }) {
  const trials = series?.trials ?? [];
  if (trials.length === 0) {
    return (
      <Fallback>
        No per-trial tape — the trial-by-trial record comes with the
        trajectories, and this run&rsquo;s could not be read.
      </Fallback>
    );
  }
  const lanes = run.conditions.map((condition) => ({
    condition,
    own: trials.filter((t) => t.triggerCode === condition.triggerCode),
  }));

  return (
    <div>
      {lanes.map(({ condition, own }) => (
        <TapeLane
          key={condition.metricId}
          label={condition.label}
          trials={trials}
          own={own}
        />
      ))}
      <div className="mt-1 flex items-baseline justify-between pl-[96px] font-mono text-[9px] tabular-nums text-static/70">
        <span>trial 1</span>
        <span>trial {trials.length}</span>
      </div>
      <p className="mt-1.5 text-[10px] leading-relaxed text-static/80">
        One tick per trial in session order, coloured by resolution; half-height
        ticks were never administered (the odor port was left early). Hover a
        tick for its time and latency.
      </p>
    </div>
  );
}

function TapeLane({
  label,
  trials,
  own,
}: {
  label: string;
  trials: TrialRecord[];
  own: TrialRecord[];
}) {
  const total = trials.length;
  // Contiguous past ~200 trials; a sliver of gap while ticks are still fat
  // enough for one to read as an event rather than a texture.
  const width = (100 / total) * (total > 200 ? 1 : 0.8);

  return (
    <div className="mt-1 flex items-center gap-2 first:mt-0">
      <span
        className="w-[88px] shrink-0 truncate text-right font-mono text-[9px] text-static/80"
        title={label}
      >
        {label}
      </span>
      <svg
        viewBox="0 0 100 12"
        preserveAspectRatio="none"
        className="h-[22px] min-w-0 flex-1"
        role="img"
        aria-label={`${label}: ${own.length} trials`}
      >
        {own.map((trial) => {
          const key = TAPE_KEY[trial.outcome] ?? null;
          return (
            <rect
              key={trial.index}
              x={(trial.index / total) * 100}
              y={key === null ? 7 : 0}
              width={width}
              height={key === null ? 5 : 12}
              fill={key === null ? "var(--color-halo)" : OUTCOME_STYLE[key].fill}
            >
              <title>{describeTrial(trial, key)}</title>
            </rect>
          );
        })}
      </svg>
    </div>
  );
}

function describeTrial(trial: TrialRecord, key: OutcomeKey | null): string {
  const what = key === null ? "aborted — never administered" : OUTCOME_STYLE[key].label;
  const parts = [`trial ${trial.index + 1} · ${what}`];
  if (trial.atMs !== null) parts.push(`at ${formatElapsed(trial.atMs)}`);
  if (trial.latencyMs !== null) parts.push(`answered in ${(trial.latencyMs / 1000).toFixed(1)}s`);
  return parts.join("\n");
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * The rolling per-condition series at full size — the sparkline's honest
 * version, on a labelled frame. The warm-up, where the window is still
 * filling, is drawn dashed and dim: a rolling proportion over three trials is
 * an artefact of the estimator, not a behaviour (`strategy_trail`'s reason).
 *
 * Each line runs over its **own** counted trials, normalized — the two
 * conditions interleave, so a shared x would need the joint clock only the
 * strategy walk carries.
 */
function TrajectoryView({ series }: { series: RunSeries | null }) {
  const metrics = (series?.metrics ?? []).filter((m) => m.values.length >= 2);
  if (metrics.length === 0) {
    return (
      <Fallback>
        No trajectory — nothing scored enough trials to draw one, or the
        run&rsquo;s file could not be read.
      </Fallback>
    );
  }

  return (
    <>
    <ChartFrame
      yTop="1.0"
      yBottom="0.0"
      xLeft="first counted trial"
      xRight="last"
      footer={
        <span className="flex items-center gap-2 truncate">
          {metrics.map((metric, index) => (
            <span key={metric.id} className="flex items-center gap-1">
              <span
                className="inline-block h-[2px] w-3"
                style={{ background: colorForIndex(index) }}
              />
              {metric.label}
            </span>
          ))}
        </span>
      }
    >
      <svg
        viewBox="0 0 100 36"
        preserveAspectRatio="none"
        className="h-[120px] w-full"
        role="img"
        aria-label="Rolling accuracy per condition over this run"
      >
        <line
          x1={0}
          y1={18}
          x2={100}
          y2={18}
          stroke="var(--color-halo)"
          strokeWidth={0.5}
          strokeDasharray="2 2"
          vectorEffect="non-scaling-stroke"
        />
        {metrics.map((metric, index) => {
          const stroke = colorForIndex(index);
          // Inset by a stroke's worth top and bottom. A perfect side bias
          // pins one line at 1.0 and the other at 0.0 — exactly the shape
          // this view most needs to show — and an un-inset unit range draws
          // both of them half outside the frame.
          const point = (value: number, i: number) =>
            `${(i / (metric.values.length - 1)) * 100},${1 + (1 - value) * 34}`;
          // The warm-up ends where the window first fills.
          const settled = metric.n.findIndex((n) => n >= metric.windowSize);
          const cut = settled === -1 ? metric.values.length - 1 : settled;
          const warmup = metric.values.slice(0, cut + 1).map(point).join(" ");
          const steady = metric.values
            .slice(cut)
            .map((value, i) => point(value, i + cut))
            .join(" ");
          return (
            <g key={metric.id}>
              <polyline
                points={warmup}
                fill="none"
                stroke={stroke}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.5}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
              <polyline
                points={steady}
                fill="none"
                stroke={stroke}
                strokeWidth={1.4}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </svg>
    </ChartFrame>
    {/* These are the task's own declared metrics, which score the **choice**
        — the correct well was answered, hold or not
        (`DATA.md#rewarded-and-response-accuracy`). They are not the
        reward rate printed on the card, and on an animal that discriminates
        well but doesn't hold the two are far apart, which is exactly when
        someone is most likely to read this line as the wrong quantity. */}
    <p className="mt-1.5 text-[10px] leading-relaxed text-static/80">
      Rolling accuracy at the task&rsquo;s authored window, scoring the
      <span className="text-static"> choice of well</span> — not whether the
      hold earned the drop. Dashed while the window is still filling.
    </p>
    </>
  );
}

/**
 * The per-odor composition spelled out — the card's bars with room for their
 * numbers. Sourced from the run's own tallies, so it renders even when the
 * series call failed.
 */
function OdorView({ run }: { run: RunSummary }) {
  if (run.conditions.length === 0 || !run.outcomes) {
    return (
      <Fallback>
        This task&rsquo;s profile can&rsquo;t express outcomes, so there is no
        per-odor split to show.
      </Fallback>
    );
  }
  const widest = Math.max(
    run.outcomes.administered,
    ...run.conditions.map((c) => c.outcomes.administered),
    1,
  );

  return (
    <div className="flex flex-col gap-2">
      {run.conditions.map((condition) => (
        <OdorRow
          key={condition.metricId}
          label={condition.label}
          outcomes={condition.outcomes}
          widest={widest}
        />
      ))}
      <OdorRow label="all trials" outcomes={run.outcomes} widest={widest} total />
    </div>
  );
}

function OdorRow({
  label,
  outcomes,
  widest,
  total = false,
}: {
  label: string;
  outcomes: ConditionOutcomes["outcomes"];
  widest: number;
  total?: boolean;
}) {
  const parts = outcomeParts(outcomes);
  return (
    <div className={total ? "border-t border-halo pt-2" : ""}>
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={`truncate text-[11px] ${total ? "text-static/80" : "text-static"}`}
        >
          {label}
        </span>
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-static/80">
          {parts.length === 0
            ? `${outcomes.administered} administered`
            : parts.map((part) => `${part.value} ${part.label}`).join(" · ")}
          {outcomes.pRewarded !== null && (
            <span style={{ color: OUTCOME_STYLE.rewarded.fill }}>
              {" "}
              · {Math.round(outcomes.pRewarded * 100)}% rewarded
            </span>
          )}
        </span>
      </div>
      {outcomes.administered > 0 && (
        <div
          className="mt-1 flex h-2.5 overflow-hidden rounded-[2px]"
          style={{ width: `${(outcomes.administered / widest) * 100}%` }}
        >
          {parts.map((part) => (
            <span
              key={part.key}
              title={`${part.value} ${part.label}`}
              style={{
                width: `${(part.value / outcomes.administered) * 100}%`,
                background: part.fill,
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The engagement ladder as a funnel (`DATA.md#engagement-ladder`) — the one
 * view that says whether a low accuracy is a discrimination problem or an
 * animal that never came to the port. Each rung's bar is its count against
 * `presented`, and the gap to the rung above is named, because the two gaps are
 * different behaviours.
 */
function EngagementView({
  run,
  color,
  revealKey,
}: {
  run: RunSummary;
  color: string;
  revealKey: string;
}) {
  const engagement = run.engagement;
  if (!engagement || !run.outcomes) {
    return (
      <Fallback>
        This task declares no trial light, so how many trials the box offered —
        and how far each got — cannot be counted.
      </Fallback>
    );
  }
  const outcomes = run.outcomes;
  const rungs = [
    { label: "offered", value: engagement.presented, drop: null },
    {
      label: "engaged the odor port",
      value: engagement.poked,
      drop: `${engagement.noPoke} never poked`,
    },
    {
      label: "reached odor delivery",
      value: engagement.odorDelivered,
      drop: `${engagement.pokeAborted} let go before odor`,
    },
    {
      label: "sampled to completion",
      value: outcomes.administered,
      drop: `${outcomes.aborted} left during sampling`,
    },
    {
      label: "rewarded",
      value: outcomes.rewarded,
      drop: `${outcomes.holdFailed + outcomes.wrongWell + outcomes.noResponse} wrong, no hold, or no answer`,
    },
  ];
  const top = Math.max(engagement.presented, 1);

  // The bar lives in a **track**, not beside the count: a rung at 100% laid
  // out as a flex sibling pushes its own number off the end of the panel.
  const RUNG_GRID =
    "grid-cols-[minmax(96px,150px)_minmax(0,1fr)_44px_minmax(0,180px)]";

  return (
    <div className="flex flex-col gap-1.5">
      {rungs.map((rung, index) => (
        <div key={rung.label} className={`grid ${RUNG_GRID} items-center gap-2`}>
          <span className="truncate text-right text-[10px] text-static" title={rung.label}>
            {rung.label}
          </span>
          {/* The width is set outright and only the fade is animated. A
              scaleX entrance multiplies against this percentage, so an
              animation that stalls — or is captured mid-flight by the export
              rasterizer — leaves the bar stating a number that isn't the
              data. A stalled fade is cosmetic; a stalled scale is a lie. */}
          <span className="h-2.5 min-w-0 overflow-hidden rounded-[2px] bg-halo/40">
            <motion.span
              key={`${revealKey}:rung:${index}`}
              className="block h-full rounded-[2px]"
              style={{
                width: `${(rung.value / top) * 100}%`,
                background: color,
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 - index * 0.12 }}
              transition={{ duration: 0.25, delay: index * 0.05 }}
            />
          </span>
          <span className="text-right font-mono text-[10px] tabular-nums text-starlight">
            {rung.value}
          </span>
          <span className="truncate font-mono text-[9px] text-static/60" title={rung.drop ?? ""}>
            {rung.drop}
          </span>
        </div>
      ))}
      <p className="mt-1 text-[10px] leading-relaxed text-static/80">
        A ladder, not a partition — each rung is how many of the offered trials
        got that far, and the note beside it is what was lost since the rung
        above.
      </p>
    </div>
  );
}

function Fallback({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] leading-relaxed text-static">{children}</p>;
}
