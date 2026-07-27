import { motion } from "framer-motion";
import { useMemo } from "react";

import { LINK_STROKE } from "@/components/chrome/constellationStyle";
import { useAnalyticsStore, useIsHighlighted, usePinnedAnimal } from "@/lib/analytics/context";
import type { AnalyticsSummary, ProfileGroup } from "@/lib/analytics/types";
import { chronological, pickMetric, runsInProfile } from "@/lib/analytics/view";

/**
 * The roster, grouped, with each animal's trend (`analytics.md` §2.3).
 *
 * Doubles as the highlight selector — hover previews, click pins — and every
 * row carries that animal's identity colour, which is the same colour its
 * curve, trail and heatmap label use.
 */
export function AnimalRail({
  summary,
  profile,
  colors,
  metricId,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  metricId: string | null;
}) {
  const trends = useMemo(
    () => buildTrends(summary, profile, metricId),
    [summary, profile, metricId],
  );

  const grouped = useMemo(() => {
    const order = new Map(summary.groups.map((g) => [g.id, g.order]));
    return [...summary.groups]
      .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0))
      .map((group) => ({
        group,
        animals: summary.animals.filter((animal) => animal.groupId === group.id),
      }))
      .filter((entry) => entry.animals.length > 0);
  }, [summary]);

  return (
    <div className="surface flex flex-col gap-3 rounded-md p-4">
      <span className="text-[11px] text-static">Animals</span>
      {grouped.map(({ group, animals }) => (
        <div key={group.id} className="flex flex-col gap-0.5">
          {grouped.length > 1 && (
            <span className="mb-0.5 font-mono text-[10px] text-static/70">{group.name}</span>
          )}
          {animals.map((animal) => (
            <AnimalRow
              key={animal.id}
              animalId={animal.id}
              name={animal.name}
              color={colors.get(animal.id) ?? "var(--color-series-1)"}
              trend={trends.get(animal.id) ?? []}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * One component instance per animal — this is what makes `useIsHighlighted`
 * cheap. Mapping animals inside a single component that called the hook once
 * would re-render the whole rail on every hover.
 */
function AnimalRow({
  animalId,
  name,
  color,
  trend,
}: {
  animalId: string;
  name: string;
  color: string;
  trend: number[];
}) {
  const store = useAnalyticsStore();
  const highlighted = useIsHighlighted(animalId);
  const pinned = usePinnedAnimal() === animalId;
  const latest = trend.length > 0 ? trend[trend.length - 1]! : null;

  return (
    <button
      type="button"
      onPointerEnter={() => store.hoverAnimal(animalId)}
      onPointerLeave={() => store.hoverAnimal(null)}
      onClick={() => store.selectAnimal(animalId)}
      className={`flex items-center gap-2 rounded-sm px-1 py-1 text-left transition-colors ${
        highlighted ? "bg-halo" : "bg-transparent"
      }`}
    >
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: color, opacity: pinned ? 1 : 0.85 }}
      />
      <span
        className={`min-w-0 flex-1 truncate text-[12px] ${
          highlighted ? "text-starlight" : "text-static"
        }`}
      >
        {name}
        {pinned && <span className="ml-1 text-pulsar">•</span>}
      </span>
      <Sparkline values={trend} color={color} />
      <span className="w-[38px] shrink-0 text-right font-mono text-[11px] tabular-nums text-starlight">
        {latest === null ? "—" : latest.toFixed(2)}
      </span>
    </button>
  );
}

/**
 * Across-session trend. Axis-less at this size on purpose, matching
 * `MetricStrip`'s sparkline: it answers "which way is this going", and the
 * number beside it answers "where is it now". The 0–1 range is fixed, so the
 * height is comparable between animals.
 */
function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return <span className="w-[54px] shrink-0" />;
  const step = 100 / (values.length - 1);
  const points = values
    .map((value, index) => `${(index * step).toFixed(2)},${((1 - value) * 30).toFixed(2)}`)
    .join(" ");
  return (
    <svg
      viewBox="0 0 100 30"
      width={54}
      height={16}
      preserveAspectRatio="none"
      className="shrink-0"
      aria-hidden
    >
      <line
        x1={0}
        y1={15}
        x2={100}
        y2={15}
        stroke={LINK_STROKE}
        strokeWidth={0.5}
        strokeDasharray="2 2"
        opacity={0.25}
        vectorEffect="non-scaling-stroke"
      />
      {/* Drawn left to right on first paint, so an animal's history arrives
          in the order it was earned rather than appearing all at once. */}
      <motion.polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      />
    </svg>
  );
}

function buildTrends(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
  metricId: string | null,
): Map<string, number[]> {
  const out = new Map<string, number[]>();
  const eligible = runsInProfile(summary.runs, profile);
  for (const animal of summary.animals) {
    const runs = chronological(
      eligible.filter((run) => run.animalId === animal.id),
      summary.sessions,
    );
    const values: number[] = [];
    for (const run of runs) {
      const metric = pickMetric(run, metricId);
      if (metric?.pSession !== null && metric?.pSession !== undefined) {
        values.push(metric.pSession);
      }
    }
    out.set(animal.id, values);
  }
  return out;
}
