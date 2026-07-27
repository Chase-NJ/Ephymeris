import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

import { getSeries } from "@/lib/analytics/commands";
import { useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import type {
  AnalyticsSummary,
  ProfileGroup,
  RunSeries,
  RunSummary,
  SessionListItem,
} from "@/lib/analytics/types";
import { declaredMetrics, poolOutcomes, runsInProfile } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/**
 * One session, per animal (`analytics.md` §3.8, §6.2).
 *
 * The panel answers "what happened in this session" at a glance, which the
 * cohort-scale views deliberately cannot: they compare sessions, this one
 * opens a single one up.
 *
 * Per animal it shows the declared conditions as within-session trajectories,
 * then the outcome breakdown those trajectories cannot express — because the
 * declared metrics are **reward-unconditional** (§3.8). An animal can score
 * well on P(R | Odor 1) while earning almost nothing, if it keeps releasing
 * the well before the fluid hold clears. The two accuracies are therefore
 * shown side by side, and the gap between them *is* the hold-failure rate.
 */

/** The trial-outcome palette. Deliberately the heat ramp's ends plus the
 *  status colours, so nothing new enters the theme for this one panel. */
const OUTCOME_STYLE = {
  rewarded: { fill: "var(--color-status-ok)", label: "rewarded" },
  holdFailed: { fill: "var(--color-status-warning)", label: "correct well, no hold" },
  wrongWell: { fill: "var(--color-status-error)", label: "wrong well" },
  noResponse: { fill: "var(--color-halo)", label: "no response" },
} as const;

export function SessionSummary({
  summary,
  profile,
  colors,
  session,
  revealKey,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  session: SessionListItem;
  revealKey: string;
}) {
  const runs = useMemo(
    () => runsInProfile(summary.runs, profile).filter((run) => run.sessionId === session.id),
    [summary, profile, session.id],
  );
  const names = useMemo(
    () => new Map(summary.animals.map((animal) => [animal.id, animal.name])),
    [summary],
  );
  const series = useRunSeries(runs);
  const conditions = declaredMetrics(profile);
  const pooled = poolOutcomes(runs);

  if (runs.length === 0) {
    return (
      <div className="surface rounded-md p-4">
        <p className="text-[12px] leading-relaxed text-static">
          No runs on {profile?.taskName ?? "this task"} in{" "}
          <span className="font-mono text-starlight">
            {session.prefixName}_{session.sessionNumber}
          </span>
          .
        </p>
      </div>
    );
  }

  return (
    <motion.div
      className="surface rounded-md p-4"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springSnappy}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="text-[11px] text-static">
          Session summary
          <span className="ml-2 font-mono text-starlight">
            {session.prefixName}_{session.sessionNumber}
          </span>
          <span className="ml-2 text-static/70">{session.date}</span>
        </span>
        <span className="font-mono text-[10px] tabular-nums text-static/80">
          {pooled.administered} administered ·{" "}
          <span style={{ color: OUTCOME_STYLE.rewarded.fill }}>
            {pooled.pRewarded === null ? "—" : pct(pooled.pRewarded)} rewarded
          </span>{" "}
          ·{" "}
          <span style={{ color: "var(--color-starlight)" }}>
            {pooled.pSide === null ? "—" : pct(pooled.pSide)} side
          </span>
        </span>
      </div>

      {/* Column headers, so the numbers below never need a legend lookup. */}
      <div className="mt-3 grid grid-cols-[minmax(64px,1fr)_repeat(3,minmax(0,1.15fr))_minmax(0,1.6fr)] items-end gap-x-3 border-b border-halo pb-1 text-[10px] text-static/70">
        <span>animal</span>
        {conditions.map((metric) => (
          <span key={metric.id} className="truncate">
            {metric.label}
          </span>
        ))}
        {conditions.length < 2 &&
          Array.from({ length: 2 - conditions.length }, (_, i) => <span key={`pad-${i}`} />)}
        <span>
          rewarded <span className="text-static/50">/ side</span>
        </span>
        <span>outcome of administered trials</span>
      </div>

      <div className="flex flex-col">
        {runs.map((run, index) => (
          <AnimalRow
            key={run.runId}
            run={run}
            name={names.get(run.animalId) ?? run.animalId}
            color={colors.get(run.animalId) ?? "var(--color-series-1)"}
            conditions={conditions.map((metric) => metric.id)}
            series={series.find((entry) => entry.runId === run.runId) ?? null}
            index={index}
            revealKey={revealKey}
          />
        ))}
      </div>

      <Legend />
    </motion.div>
  );
}

/**
 * One animal's row. A separate component per animal because that is what the
 * cross-panel highlight scheme requires (`context.ts`'s `useIsHighlighted`
 * invariant) — a single component looping over animals would silently lose it.
 */
function AnimalRow({
  run,
  name,
  color,
  conditions,
  series,
  index,
  revealKey,
}: {
  run: RunSummary;
  name: string;
  color: string;
  conditions: string[];
  series: RunSeries | null;
  index: number;
  revealKey: string;
}) {
  const store = useAnalyticsStore();
  const highlighted = useIsHighlighted(run.animalId);
  const outcomes = run.outcomes;

  return (
    <motion.div
      className={`grid grid-cols-[minmax(64px,1fr)_repeat(3,minmax(0,1.15fr))_minmax(0,1.6fr)] items-center gap-x-3 rounded-sm px-1 py-1.5 transition-colors ${
        highlighted ? "bg-halo" : ""
      }`}
      onPointerEnter={() => store.hoverAnimal(run.animalId)}
      onPointerLeave={() => store.hoverAnimal(null)}
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ ...springSnappy, delay: index * 0.05 }}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ background: color, opacity: highlighted ? 1 : 0.85 }}
        />
        <span
          className={`truncate text-[12px] ${highlighted ? "text-starlight" : "text-static"}`}
        >
          {name}
        </span>
      </span>

      {/* The declared conditions, as within-session trajectories. */}
      {conditions.map((metricId) => (
        <ConditionSpark
          key={metricId}
          values={series?.metrics.find((m) => m.id === metricId)?.values ?? []}
          color={color}
          revealKey={`${revealKey}:${run.runId}:${metricId}`}
        />
      ))}
      {conditions.length < 2 &&
        Array.from({ length: 2 - conditions.length }, (_, i) => <span key={`pad-${i}`} />)}

      {/* The third figure the conditions cannot give: what was actually earned. */}
      <span className="font-mono text-[11px] tabular-nums">
        {outcomes === null ? (
          <span className="text-static/60">—</span>
        ) : (
          <>
            <span style={{ color: OUTCOME_STYLE.rewarded.fill }}>
              {outcomes.pRewarded === null ? "—" : pct(outcomes.pRewarded)}
            </span>
            <span className="text-static/50"> / </span>
            <span className="text-starlight">
              {outcomes.pSide === null ? "—" : pct(outcomes.pSide)}
            </span>
          </>
        )}
      </span>

      <OutcomeBar run={run} index={index} revealKey={revealKey} />
    </motion.div>
  );
}

/** A within-session trajectory, drawn on rather than snapped in. */
function ConditionSpark({
  values,
  color,
  revealKey,
}: {
  values: number[];
  color: string;
  revealKey: string;
}) {
  if (values.length < 2) {
    return <span className="font-mono text-[10px] text-static/50">—</span>;
  }
  const points = values
    .map((value, index) => `${(index / (values.length - 1)) * 100},${(1 - value) * 18}`)
    .join(" ");
  return (
    <svg
      viewBox="0 0 100 18"
      preserveAspectRatio="none"
      className="h-[18px] w-full"
      aria-hidden
    >
      <line
        x1={0}
        y1={9}
        x2={100}
        y2={9}
        stroke="var(--color-halo)"
        strokeWidth={0.5}
        strokeDasharray="2 2"
        vectorEffect="non-scaling-stroke"
      />
      <motion.polyline
        key={revealKey}
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.2}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.7, ease: "easeOut" }}
      />
    </svg>
  );
}

/**
 * How the administered trials resolved, as one stacked bar.
 *
 * The bar's width is the *administered* count relative to the widest animal in
 * the session, so a rat that engaged with half as many trials reads as half a
 * bar rather than as a full bar of different proportions — the count and the
 * composition are both part of the story.
 */
function OutcomeBar({
  run,
  index,
  revealKey,
}: {
  run: RunSummary;
  index: number;
  revealKey: string;
}) {
  const outcomes = run.outcomes;
  if (!outcomes || outcomes.administered === 0) {
    return (
      <span className="font-mono text-[10px] text-static/50">
        {outcomes ? `${outcomes.aborted} aborted, none administered` : "no outcome data"}
      </span>
    );
  }

  const parts = [
    { key: "rewarded" as const, value: outcomes.rewarded },
    { key: "holdFailed" as const, value: outcomes.holdFailed },
    { key: "wrongWell" as const, value: outcomes.wrongWell },
    { key: "noResponse" as const, value: outcomes.noResponse },
  ].filter((part) => part.value > 0);

  return (
    <span className="flex items-center gap-2">
      <motion.span
        key={revealKey}
        className="flex h-3 min-w-0 flex-1 overflow-hidden rounded-[2px]"
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ ...springSnappy, delay: index * 0.05 + 0.1 }}
        style={{ transformOrigin: "left center" }}
      >
        {parts.map((part) => (
          <span
            key={part.key}
            title={`${part.value} ${OUTCOME_STYLE[part.key].label}`}
            style={{
              width: `${(part.value / outcomes.administered) * 100}%`,
              background: OUTCOME_STYLE[part.key].fill,
            }}
          />
        ))}
      </motion.span>
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-static/80">
        {outcomes.administered}
      </span>
    </span>
  );
}

function Legend() {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-halo pt-2 font-mono text-[9px] text-static/70">
      {Object.entries(OUTCOME_STYLE).map(([key, style]) => (
        <span key={key} className="flex items-center gap-1">
          <span
            className="inline-block size-2 rounded-[2px]"
            style={{ background: style.fill }}
          />
          {style.label}
        </span>
      ))}
      <span className="ml-auto">
        rewarded = fluid delivered · side = correct well reached, hold or not
      </span>
    </div>
  );
}

/**
 * The within-session trajectories for these runs.
 *
 * Keyed on the joined run ids so the effect is stable across the re-renders a
 * hover causes — the same idiom `LearningCurves` uses.
 */
function useRunSeries(runs: RunSummary[]): RunSeries[] {
  const { client } = useSidecar();
  const [series, setSeries] = useState<RunSeries[]>([]);
  const ids = runs.map((run) => run.runId).join(",");

  useEffect(() => {
    if (!ids) {
      setSeries([]);
      return;
    }
    let live = true;
    void getSeries(client, ids.split(","))
      .then((result) => live && setSeries(result.series))
      .catch(() => live && setSeries([]));
    return () => {
      live = false;
    };
  }, [client, ids]);

  return series;
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
