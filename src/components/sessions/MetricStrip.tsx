import { LINK_STROKE } from "@/components/chrome/constellationStyle";
import { useMetricHistory } from "@/lib/sessions/context";
import type { TelemetryMetric } from "@/lib/sessions/types";

/**
 * Live rolling metrics for one box (`tasks.md` §5).
 *
 * A sketch with no Task Profile has no metrics to show — the doc's fallback is
 * the raw strobe log, which Debug Mode already provides, so this says so rather
 * than rendering an empty frame.
 */
export function MetricStrip({
  box,
  metrics,
  bare = false,
}: {
  box: number;
  metrics: TelemetryMetric[];
  /**
   * True inside a section that already provides its own chrome (`StarPanel`'s
   * Live metrics card) — drops the tile-flow margin and divider the strip
   * carries when it sits at the bottom of a `BoxCard`.
   */
  bare?: boolean;
}) {
  if (metrics.length === 0) {
    return (
      <p className={`text-[11px] text-static ${bare ? "" : "mt-3"}`}>
        No live metrics yet — they appear once trials start counting.
      </p>
    );
  }
  return (
    <div
      className={`flex flex-col gap-2 ${bare ? "" : "mt-3 border-t border-halo pt-3"}`}
    >
      {metrics.map((metric) => (
        <MetricRow key={metric.id} box={box} metric={metric} />
      ))}
    </div>
  );
}

function MetricRow({ box, metric }: { box: number; metric: TelemetryMetric }) {
  const history = useMetricHistory(box, metric.id);
  return (
    <div className="flex items-center gap-3">
      <span className="min-w-0 flex-1 truncate text-[11px] text-static">{metric.id}</span>
      <Sparkline history={history} />
      <span className="w-[52px] text-right font-mono text-[12px] tabular-nums text-starlight">
        {metric.value === null ? "—" : metric.value.toFixed(2)}
      </span>
      <span className="w-[42px] text-right font-mono text-[10px] tabular-nums text-static">
        n={metric.n}
      </span>
    </div>
  );
}

/**
 * The rolling value over time. Deliberately axis-less at this size — it answers
 * "which way is this animal trending"; the number beside it answers "where is
 * it now". The 0–1 range is fixed, so height is comparable across boxes.
 */
function Sparkline({ history }: { history: number[] }) {
  if (history.length < 2) return <span className="w-[90px]" />;

  const step = 100 / (history.length - 1);
  const points = history
    .map((value, index) => `${(index * step).toFixed(2)},${((1 - value) * 30).toFixed(2)}`)
    .join(" ");

  return (
    <svg viewBox="0 0 100 30" width={90} height={22} preserveAspectRatio="none" aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke={LINK_STROKE}
        strokeWidth={1.5}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
