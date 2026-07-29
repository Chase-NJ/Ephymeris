import { motion } from "framer-motion";
import { useMemo } from "react";

import { DrawOn } from "@/components/charts/DrawOn";
import { useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import type {
  AnalyticsSummary,
  ConditionOutcomes,
  MetricSummary,
  ProfileGroup,
  RunSeries,
  RunSummary,
  SessionListItem,
  TrialOutcomes,
} from "@/lib/analytics/types";
import { OUTCOME_STYLE, declaredMetrics, poolOutcomes } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";

/**
 * One session, per animal (`analytics.md` §3.8, §3.9, §6.3).
 *
 * The panel answers "what happened in this session" at a glance, which the
 * cohort-scale views deliberately cannot: they compare sessions, this one
 * opens a single one up.
 *
 * **One card per animal, not one row.** The per-condition counts (§3.9) need a
 * second dimension — a row carrying trials, administered, two conditions'
 * administered and rewarded counts, two trajectories and two bars is a row
 * nobody can read.
 *
 * Each card reads top to bottom as: the effort (trials, administered,
 * aborted), then each declared condition's own administered/rewarded counts
 * with its trajectory, then the two accuracies as one bar, then how the
 * administered trials resolved. The accuracies come last of the numbers
 * because `administered` is their denominator and is stated first.
 */

export function SessionSummary({
  summary,
  profile,
  colors,
  session,
  runs,
  series,
  revealKey,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  session: SessionListItem;
  runs: RunSummary[];
  series: RunSeries[];
  revealKey: string;
}) {
  const names = useMemo(
    () => new Map(summary.animals.map((animal) => [animal.id, animal.name])),
    [summary],
  );
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

      <div className="mt-3 grid grid-cols-1 gap-2 xl:grid-cols-2">
        {runs.map((run, index) => (
          <AnimalCard
            key={run.runId}
            run={run}
            name={names.get(run.animalId) ?? run.animalId}
            color={colors.get(run.animalId) ?? "var(--color-series-1)"}
            conditions={conditions}
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
 * One animal's card. A separate component per animal because that is what the
 * cross-panel highlight scheme requires (`context.ts`'s `useIsHighlighted`
 * invariant) — a single component looping over animals would silently lose it.
 */
function AnimalCard({
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
  conditions: ProfileGroup["metrics"];
  series: RunSeries | null;
  index: number;
  revealKey: string;
}) {
  const store = useAnalyticsStore();
  const highlighted = useIsHighlighted(run.animalId);
  const outcomes = run.outcomes;
  const byMetric = new Map(run.conditions.map((entry) => [entry.metricId, entry]));

  return (
    <motion.div
      className={`rounded-sm border px-3 py-2.5 transition-colors ${
        highlighted ? "border-static/40 bg-halo/50" : "border-halo"
      }`}
      onPointerEnter={() => store.hoverAnimal(run.animalId)}
      onPointerLeave={() => store.hoverAnimal(null)}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...springSnappy, delay: index * 0.04 }}
    >
      <div className="flex items-baseline justify-between gap-3">
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
        <Effort outcomes={outcomes} />
      </div>

      {/* Per condition (§3.9): how many trials of this kind were administered,
          and how many of those paid out. */}
      <div className="mt-2 grid grid-cols-[minmax(0,1fr)_72px_60px_minmax(52px,1fr)] items-center gap-x-2 border-b border-halo pb-1 font-mono text-[9px] text-static/70">
        <span>condition</span>
        <span className="text-right">administered</span>
        <span className="text-right">rewarded</span>
        <span className="text-right">trajectory</span>
      </div>
      {conditions.map((metric) => (
        <ConditionRow
          key={metric.id}
          label={metric.label}
          condition={byMetric.get(metric.id) ?? null}
          fallback={run.metrics.find((m) => m.id === metric.id) ?? null}
          values={series?.metrics.find((m) => m.id === metric.id)?.values ?? []}
          color={color}
          revealKey={`${revealKey}:${run.runId}:${metric.id}`}
        />
      ))}

      <RewardGap outcomes={outcomes} index={index} revealKey={revealKey} />
      <OutcomeBar outcomes={outcomes} index={index} revealKey={revealKey} />
    </motion.div>
  );
}

/**
 * Trials, administered, aborted — the header every rate below is a fraction of.
 *
 * `trials` and `administered` are both shown because they are different facts:
 * 200 trials with 90 administered is a very different session from 200 with
 * 195 at identical accuracy (§3.8).
 */
function Effort({ outcomes }: { outcomes: TrialOutcomes | null }) {
  if (!outcomes) {
    return <span className="font-mono text-[10px] text-static/50">no outcome data</span>;
  }
  return (
    <span className="shrink-0 font-mono text-[10px] tabular-nums text-static/80">
      <span className="text-starlight">{outcomes.trials}</span> trials ·{" "}
      <span className="text-starlight">{outcomes.administered}</span> administered
      {outcomes.aborted > 0 && <> · {outcomes.aborted} aborted</>}
    </span>
  );
}

/**
 * One declared condition's counts and trajectory.
 *
 * When the profile declares no reward vocabulary there is no per-condition
 * tally to show (§3.9), so the row falls back to the metric's own scored-trial
 * count and says nothing at all about rewards — a dash rather than a zero,
 * because "this task has no notion of a reward" is not "none was earned".
 */
function ConditionRow({
  label,
  condition,
  fallback,
  values,
  color,
  revealKey,
}: {
  label: string;
  condition: ConditionOutcomes | null;
  fallback: MetricSummary | null;
  values: number[];
  color: string;
  revealKey: string;
}) {
  const administered = condition ? condition.outcomes.administered : (fallback?.counted ?? null);
  const rewarded = condition ? condition.outcomes.rewarded : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_72px_60px_minmax(52px,1fr)] items-center gap-x-2 py-1">
      <span className="truncate text-[11px] text-static" title={label}>
        {label}
      </span>
      <span className="text-right font-mono text-[11px] tabular-nums text-starlight">
        {administered ?? "—"}
      </span>
      <span
        className="text-right font-mono text-[11px] tabular-nums"
        style={{ color: rewarded === null ? undefined : OUTCOME_STYLE.rewarded.fill }}
      >
        {rewarded ?? <span className="text-static/50">—</span>}
      </span>
      <ConditionSpark values={values} color={color} revealKey={revealKey} />
    </div>
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
    return <span className="text-right font-mono text-[10px] text-static/50">—</span>;
  }
  const points = values
    .map((value, index) => `${(index / (values.length - 1)) * 100},${(1 - value) * 18}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 18" preserveAspectRatio="none" className="h-[18px] w-full" aria-hidden>
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
      <DrawOn key={revealKey} viewBox={[0, 0, 100, 18]} duration={0.7}>
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth={1.2}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </DrawOn>
    </svg>
  );
}

/**
 * Rewarded accuracy against side accuracy, as **one** bar (§6.3).
 *
 * Side accuracy is `(rewarded + holdFailed) / administered` and rewarded is
 * `rewarded / administered`, so the second is a strict subset of the first —
 * always ≥, never crossing. Two separate bars would invite reading the
 * difference as a comparison of unrelated quantities; drawing rewarded as a
 * filled span *inside* the side span makes the containment structural, and the
 * remaining segment **is** the hold-failure rate rather than a subtraction the
 * reader has to perform.
 *
 * That segment carries `holdFailed`'s colour from the outcome bar below, so
 * the same behaviour is the same colour in both places on the card.
 */
function RewardGap({
  outcomes,
  index,
  revealKey,
}: {
  outcomes: TrialOutcomes | null;
  index: number;
  revealKey: string;
}) {
  if (!outcomes || outcomes.administered === 0) return null;
  const rewarded = outcomes.pRewarded ?? 0;
  const side = outcomes.pSide ?? 0;
  const gap = Math.max(0, side - rewarded);

  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between gap-2 font-mono text-[9px] text-static/70">
        <span>rewarded vs side</span>
        <span className="tabular-nums">
          <span style={{ color: OUTCOME_STYLE.rewarded.fill }}>{pct(rewarded)}</span>
          <span className="text-static/50"> → </span>
          <span className="text-starlight">{pct(side)}</span>
          {gap > 0 && (
            <span style={{ color: OUTCOME_STYLE.holdFailed.fill }}>
              {" "}
              · {pct(gap)} no hold
            </span>
          )}
        </span>
      </div>
      <motion.div
        key={`${revealKey}:gap`}
        className="mt-0.5 flex h-2 overflow-hidden rounded-[2px] bg-halo/60"
        title={`${outcomes.rewarded} rewarded and ${outcomes.holdFailed} correct-well-no-hold of ${outcomes.administered} administered`}
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ ...springSnappy, delay: index * 0.04 + 0.1 }}
        style={{ transformOrigin: "left center" }}
      >
        <span
          style={{ width: `${rewarded * 100}%`, background: OUTCOME_STYLE.rewarded.fill }}
        />
        {/* The gap between the two accuracies: the correct side was chosen and
            no drop was earned. */}
        <span
          style={{ width: `${gap * 100}%`, background: OUTCOME_STYLE.holdFailed.fill }}
        />
      </motion.div>
    </div>
  );
}

/**
 * How the administered trials resolved, as one stacked bar.
 *
 * Scaled by the **administered count** against the widest bar the card can
 * show, so composition and effort are both legible: a rat that engaged with
 * half as many trials reads as half a bar rather than a full bar of different
 * proportions.
 */
function OutcomeBar({
  outcomes,
  index,
  revealKey,
}: {
  outcomes: TrialOutcomes | null;
  index: number;
  revealKey: string;
}) {
  if (!outcomes || outcomes.administered === 0) {
    return (
      <p className="mt-2 font-mono text-[10px] text-static/50">
        {outcomes ? `${outcomes.aborted} aborted, none administered` : "no outcome data"}
      </p>
    );
  }

  const parts = [
    { key: "rewarded" as const, value: outcomes.rewarded },
    { key: "holdFailed" as const, value: outcomes.holdFailed },
    { key: "wrongWell" as const, value: outcomes.wrongWell },
    { key: "noResponse" as const, value: outcomes.noResponse },
  ].filter((part) => part.value > 0);

  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between gap-2 font-mono text-[9px] text-static/70">
        <span>outcome of administered</span>
        <span className="tabular-nums">{outcomes.administered}</span>
      </div>
      <motion.div
        key={`${revealKey}:outcome`}
        className="mt-0.5 flex h-2 overflow-hidden rounded-[2px]"
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ ...springSnappy, delay: index * 0.04 + 0.15 }}
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
      </motion.div>
    </div>
  );
}

function Legend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-halo pt-2 font-mono text-[9px] text-static/70">
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

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
