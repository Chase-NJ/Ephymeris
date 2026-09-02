import { PawPrint } from "lucide-react";
import { useMemo } from "react";

import { DrawOn } from "@/components/charts/DrawOn";
import { LINK_STROKE } from "@/components/chrome/constellationStyle";
import { useAnalyticsStore, useIsHighlighted, usePinnedAnimal } from "@/lib/analytics/context";
import type { AnalyticsSummary } from "@/lib/analytics/types";
import { chronological, pickMetric } from "@/lib/analytics/view";

/**
 * The roster, grouped, with each animal's trend (`data.md` §10.3).
 *
 * Doubles as the highlight selector — hover previews, click pins — and every
 * row carries that animal's identity colour, which is the same colour its
 * curve and trail use.
 */
export function AnimalRail({
  summary,
  colors,
  scroll = true,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
  /**
   * Whether the rail caps at its row's height and scrolls, or grows to fit.
   *
   * Capped, it is lifted out of flow (`absolute`) inside a stretched wrapper.
   * That is what makes the cap possible without measuring anything: the
   * wrapper takes its height from the strategy tile beside it, `max-h-full`
   * resolves against that, and a rail contributing **zero** height can never
   * stretch the row it is trying to match. Under the cap the height stays
   * `auto`, so a two-animal cohort gets a compact card rather than a tall
   * empty one.
   *
   * A report sheet passes `false`, for the reason `CohortHeatmap`'s `scroll`
   * prop documents: a rasterizer captures a scroll container as whatever was
   * in view, so a long roster would lose animals off the bottom of the PNG
   * with nothing to show it had happened.
   *
   * Only applied from `lg` up. Below it the two-column grid collapses, and an
   * absolute rail whose wrapper has no sibling to give it height would fall to
   * zero and sit on top of the panel beneath.
   */
  scroll?: boolean;
}) {
  const trends = useMemo(() => buildTrends(summary), [summary]);

  const grouped = useMemo(() => {
    const order = new Map(summary.groups.map((g) => [g.id, g.order]));
    return [...summary.groups]
      .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0))
      .map((group) => ({
        group,
        animals: summary.animals
          .filter((animal) => animal.groupId === group.id)
          // Numeric-aware, the session summary's rule: remy2 before remy10.
          .sort((a, b) => collator.compare(a.name, b.name)),
      }))
      .filter((entry) => entry.animals.length > 0);
  }, [summary]);

  return (
    <div
      className={`surface flex flex-col gap-3 rounded-md p-4 ${
        scroll ? "lg:absolute lg:inset-x-0 lg:top-0 lg:max-h-full" : ""
      }`}
    >
      <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-static">
        <PawPrint size={13} strokeWidth={1.75} className="text-pulsar" />
        Animals
      </span>
      {/* The groups live in their own box so the heading stays put while they
          scroll, and so spacing is identical either way — the root's `gap-3`
          used to separate the heading and every group, and this now owns the
          second half of that job. `pr-1` is the gutter for the 10px scrollbar
          `styles/index.css` gives every scroller. */}
      <div
        className={`flex flex-col gap-3 ${
          scroll ? "min-h-0 flex-1 overflow-y-auto pr-1" : ""
        }`}
      >
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
          in the order it was earned rather than appearing all at once.
          Wiped rather than `pathLength`-drawn: this rail is the one chart
          rendered *smaller* than its viewBox, which is the only reason that
          approach didn't shatter the line here the way it did everywhere else
          (see `DrawOn`) — and widening the rail would have been enough to
          break it. */}
      <DrawOn viewBox={[0, 0, 100, 30]} duration={0.8}>
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </DrawOn>
    </svg>
  );
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/**
 * Every animal's whole history — all tasks, each run at its pooled overall
 * accuracy (§3.7). The sparkline answers "which way is this going", and a
 * history that silently skipped every session on another task would answer it
 * about a different animal than the one in the room.
 */
function buildTrends(summary: AnalyticsSummary): Map<string, number[]> {
  const out = new Map<string, number[]>();
  for (const animal of summary.animals) {
    const runs = chronological(
      summary.runs.filter((run) => run.animalId === animal.id),
      summary.sessions,
    );
    const values: number[] = [];
    for (const run of runs) {
      const metric = pickMetric(run, null);
      if (metric?.pSession !== null && metric?.pSession !== undefined) {
        values.push(metric.pSession);
      }
    }
    out.set(animal.id, values);
  }
  return out;
}
