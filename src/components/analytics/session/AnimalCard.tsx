import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";

import { DrawOn } from "@/components/charts/DrawOn";
import { useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import {
  formatClock,
  outcomeParts,
  programOf,
  runEnd,
  unscoredReason,
} from "@/lib/analytics/session";
import type {
  ConditionOutcomes,
  MetricSummary,
  RunSeries,
  RunSummary,
  TrialEngagement,
  TrialOutcomes,
} from "@/lib/analytics/types";
import { OUTCOME_STYLE } from "@/lib/analytics/view";
import { springPanel, springSnappy } from "@/lib/motion";

import { AnimalDetail } from "./AnimalDetail";

/**
 * One animal's card (`data.md` §11.4). A separate component per animal because
 * that is what the cross-panel highlight scheme requires (`context.ts`'s
 * `useIsHighlighted` invariant) — a single component looping over animals
 * would silently lose it.
 *
 * The card reads top to bottom as: who and on what program, the effort, then
 * each declared condition's administered/rewarded counts with **how those
 * trials resolved** and the condition's trajectory, then the whole run's
 * resolution as one bar — so the odor rows visibly sum into it. Clicking the
 * card opens the per-animal detail views (`AnimalDetail`).
 */
export function AnimalCard({
  run,
  name,
  color,
  series,
  index,
  revealKey,
  expanded,
  onToggle,
}: {
  run: RunSummary;
  name: string;
  color: string;
  series: RunSeries | null;
  index: number;
  revealKey: string;
  expanded: boolean;
  /** Null renders the card inert — the export sheet cannot be clicked. */
  onToggle: ((runId: string) => void) | null;
}) {
  const store = useAnalyticsStore();
  const highlighted = useIsHighlighted(run.animalId);
  const outcomes = run.outcomes;
  const reason = unscoredReason(run);
  // A run with nothing to score has nothing to expand into, so it offers no
  // affordance to try — a chevron that opens an empty drawer is worse than
  // no chevron.
  const toggle = reason ? null : onToggle;
  const byMetric = new Map(run.conditions.map((entry) => [entry.metricId, entry]));
  // The widest condition on this card — every per-odor bar is scaled against
  // it, so a rarely-presented odor reads as a short bar rather than a full
  // bar of misleading proportions (the run-level bar's own rule).
  const widest = Math.max(
    1,
    ...run.conditions.map((entry) => entry.outcomes.administered),
  );

  return (
    <motion.div
      id={`session-animal-${run.runId}`}
      layout
      className={`min-w-0 rounded-sm border transition-colors ${
        expanded
          ? "border-static/40 xl:col-span-2"
          : highlighted
            ? "border-static/40 bg-halo/50"
            : "border-halo"
      } ${reason ? "opacity-60" : ""}`}
      onPointerEnter={() => store.hoverAnimal(run.animalId)}
      onPointerLeave={() => store.hoverAnimal(null)}
      initial={{ opacity: 0, y: 4 }}
      // The stagger belongs to the entrance alone, spelled inside the target:
      // the top-level `transition` also governs the `layout` glide to and from
      // the focus slot, and a per-index delay there turns the promotion into a
      // laggy shuffle. The glide itself gets the panel spring — it is a card
      // travelling across the grid, not a small control settling.
      animate={{
        opacity: 1,
        y: 0,
        transition: { ...springSnappy, delay: index * 0.04 },
      }}
      transition={{ ...springSnappy, layout: springPanel }}
    >
      <div
        className={`px-3 py-2.5 ${toggle ? "cursor-pointer" : ""}`}
        role={toggle ? "button" : undefined}
        tabIndex={toggle ? 0 : undefined}
        aria-expanded={toggle ? expanded : undefined}
        onClick={toggle ? () => toggle(run.runId) : undefined}
        onKeyDown={
          toggle
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggle(run.runId);
                }
              }
            : undefined
        }
      >
        {/* Identity first, effort on its own line below it. One row for both
            crushed the name to an ellipsis on any card whose effort string ran
            long — and the name is the one thing on the card that must never
            be the part that gets truncated. */}
        <div className="flex items-baseline justify-between gap-2">
          <span className="flex min-w-0 items-baseline gap-1.5">
            <span
              className="size-2 shrink-0 translate-y-px rounded-full"
              style={{ background: color, opacity: highlighted ? 1 : 0.85 }}
            />
            <span
              className={`shrink-0 text-[12px] ${highlighted ? "text-starlight" : "text-static"}`}
            >
              {name}
            </span>
            {/* The program, always — a mixed-task session must be legible
                without cross-referencing the table. */}
            <span
              className="min-w-0 truncate rounded-[2px] border border-halo px-1 py-px font-mono text-[9px] text-static/80"
              title={run.sketchPath}
            >
              {programOf(run)}
            </span>
            {run.boxNumber !== null && (
              <span className="shrink-0 font-mono text-[9px] text-static/60">
                box {run.boxNumber}
              </span>
            )}
          </span>
          {toggle && (
            <motion.span
              animate={{ rotate: expanded ? 180 : 0 }}
              transition={springSnappy}
              className="shrink-0 text-static/60"
              aria-hidden
            >
              <ChevronDown size={13} strokeWidth={1.75} />
            </motion.span>
          )}
        </div>
        {/* An unscored run says why below; "no outcome data" above it would
            be the same sentence twice. */}
        {!reason && (
          <div className="mt-0.5">
            <Effort outcomes={outcomes} engagement={run.engagement} />
          </div>
        )}

        {reason ? (
          <Unscored run={run} reason={reason} />
        ) : (
          <>
            {/* Per condition (§3.9, §9.8): how many trials of this kind were
                administered, how many paid out, and — the classification the
                whole card is for — how the administered ones resolved. */}
            <div
              className={`mt-2 grid ${CONDITION_GRID} items-center gap-x-2 border-b border-halo pb-1 font-mono text-[9px] text-static/70`}
            >
              <span>condition</span>
              <span className="text-right">admin.</span>
              <span className="text-right">rewarded</span>
              <span>outcomes</span>
              <span className="text-right">trajectory</span>
            </div>
            {run.metrics.map((metric) => (
              <ConditionRow
                key={metric.id}
                label={metric.label}
                condition={byMetric.get(metric.id) ?? null}
                fallback={metric}
                widest={widest}
                values={series?.metrics.find((m) => m.id === metric.id)?.values ?? []}
                color={color}
                revealKey={`${revealKey}:${run.runId}:${metric.id}`}
              />
            ))}

            <OutcomeBar outcomes={outcomes} index={index} revealKey={revealKey} />
          </>
        )}
      </div>

      {/* The drawer slides open rather than popping in: height animates to
          measured auto and back to zero, clipped while in motion. `initial=
          {false}` so a card that mounts already-open (never today, cheap
          insurance) doesn't replay the reveal. On a swap, the closing card's
          exit runs while the opening card's entrance does — one continuous
          hand-off instead of a cut. */}
      <AnimatePresence initial={false}>
        {expanded && !reason && (
          <motion.div
            key="detail"
            className="overflow-hidden"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springPanel}
          >
            <AnimalDetail
              run={run}
              series={series}
              color={color}
              revealKey={revealKey}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/**
 * The card of a run that can't be scored — muted, with the reason, never a
 * row of zeroes. "This animal earned nothing" and "we cannot say" are
 * different claims, and a zeroed card asserts the first (§9.8's rule).
 */
function Unscored({ run, reason }: { run: RunSummary; reason: string }) {
  const end = runEnd(run);
  return (
    <p className="mt-2 font-mono text-[10px] leading-relaxed text-static/70">
      {formatClock(run.startedAt)} → {end.derived && "~"}
      {end.text} ·{" "}
      <span style={{ color: "var(--color-status-warning)" }}>not scored</span> —{" "}
      {reason}
    </p>
  );
}

/**
 * Offered, trials, administered — the header every rate below is a fraction
 * of. All three are shown because they are different facts: 200 trials with 90
 * administered is a very different session from 200 with 195 at identical
 * accuracy (§3.8), and 300 *offered* with 200 reaching odor is different
 * again (§3.10).
 */
function Effort({
  outcomes,
  engagement,
}: {
  outcomes: TrialOutcomes | null;
  engagement: TrialEngagement | null;
}) {
  if (!outcomes) {
    return <span className="font-mono text-[10px] text-static/50">no outcome data</span>;
  }
  return (
    <span
      className="font-mono text-[10px] tabular-nums text-static/80"
      title={engagement ? describeEngagement(engagement) : undefined}
    >
      {engagement && (
        <>
          <span className="text-starlight">{engagement.presented}</span> offered ·{" "}
        </>
      )}
      <span className="text-starlight">{outcomes.trials}</span> trials ·{" "}
      <span className="text-starlight">{outcomes.administered}</span> administered
      {outcomes.aborted > 0 && <> · {outcomes.aborted} aborted</>}
    </span>
  );
}

/** The engagement ladder spelled out (§9.10) — the two gaps are different
 *  behaviours, and the header line only has room for their endpoints. */
function describeEngagement(engagement: TrialEngagement): string {
  const rate =
    engagement.pEngaged === null ? "—" : `${Math.round(engagement.pEngaged * 100)}%`;
  return (
    `${engagement.presented} trials offered · ${rate} engaged\n` +
    `${engagement.noPoke} never poked the odor port\n` +
    `${engagement.pokeAborted} poked, let go before odor delivery`
  );
}

/** Shared column template for the per-condition header and rows. */
const CONDITION_GRID =
  "grid-cols-[minmax(0,1fr)_40px_76px_minmax(64px,1.2fr)_minmax(44px,1fr)]";

/**
 * One declared condition's counts, resolution and trajectory.
 *
 * `rewarded` reads `count · rate` over **this condition's** administered
 * trials; the stacked bar beside it is those same administered trials split
 * by how they resolved — failed the hold, wrong well, or no answer — in the
 * run bar's colours, so the same behaviour is the same colour everywhere on
 * the card.
 *
 * When the profile declares no reward vocabulary there is no per-condition
 * tally to show (§9.9), so the row falls back to the metric's own
 * scored-trial count and says nothing about outcomes — a dash rather than a
 * zero, because "this task has no notion of a reward" is not "none was
 * earned".
 */
function ConditionRow({
  label,
  condition,
  fallback,
  widest,
  values,
  color,
  revealKey,
}: {
  label: string;
  condition: ConditionOutcomes | null;
  fallback: MetricSummary | null;
  widest: number;
  values: number[];
  color: string;
  revealKey: string;
}) {
  const administered = condition ? condition.outcomes.administered : (fallback?.counted ?? null);
  const rewarded = condition ? condition.outcomes.rewarded : null;
  const pRewarded = condition?.outcomes.pRewarded ?? null;

  return (
    <div className={`grid ${CONDITION_GRID} items-center gap-x-2 py-1`}>
      <span className="truncate text-[11px] text-static" title={label}>
        {label}
      </span>
      <span className="text-right font-mono text-[11px] tabular-nums text-starlight">
        {administered ?? "—"}
      </span>
      {rewarded === null ? (
        <span className="text-right font-mono text-[11px] tabular-nums text-static/50">
          —
        </span>
      ) : (
        <span
          className="text-right font-mono text-[11px] tabular-nums"
          style={{ color: OUTCOME_STYLE.rewarded.fill }}
          title={`${rewarded} of ${administered ?? 0} administered ${label} trials rewarded`}
        >
          {rewarded}
          <span className="text-[9px] opacity-70">
            {" "}
            · {pRewarded === null ? "—" : pct(pRewarded)}
          </span>
        </span>
      )}
      <ConditionOutcomeBar condition={condition} widest={widest} label={label} />
      <ConditionSpark values={values} color={color} revealKey={revealKey} />
    </div>
  );
}

/**
 * How one condition's administered trials resolved — the per-odor version of
 * the run-level bar, in the same colours and under the same scaling rule:
 * width against the card's widest condition, so composition and effort are
 * both legible.
 */
function ConditionOutcomeBar({
  condition,
  widest,
  label,
}: {
  condition: ConditionOutcomes | null;
  widest: number;
  label: string;
}) {
  if (!condition || condition.outcomes.administered === 0) {
    return <span className="font-mono text-[10px] text-static/50">—</span>;
  }
  const parts = outcomeParts(condition.outcomes);
  const administered = condition.outcomes.administered;
  return (
    <div
      className="flex h-2 overflow-hidden rounded-[2px]"
      style={{ width: `${(administered / widest) * 100}%` }}
      title={parts
        .map((part) => `${part.value} ${part.label}`)
        .join(" · ")
        .concat(` — of ${administered} administered ${label} trials`)}
    >
      {parts.map((part) => (
        <span
          key={part.key}
          style={{
            width: `${(part.value / administered) * 100}%`,
            background: part.fill,
          }}
        />
      ))}
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
 * How the whole run's administered trials resolved, as one stacked bar — the
 * total the per-odor rows above visibly sum into. Full width: the per-odor
 * bars carry the relative-effort scaling, and scaling this one too would
 * leave nothing at full width to read the others against.
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
  const parts = outcomeParts(outcomes);

  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between gap-2 font-mono text-[9px] text-static/70">
        <span>all administered trials</span>
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
            title={`${part.value} ${part.label}`}
            style={{
              width: `${(part.value / outcomes.administered) * 100}%`,
              background: part.fill,
            }}
          />
        ))}
      </motion.div>
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
