import { LINK_STROKE, NODE_ACCENT } from "@/components/chrome/constellationStyle";
import type { LiveMetric, TelemetryMetric } from "@/lib/sessions/types";

/**
 * One live metric's rolling line chart (`starting-a-session.md` §6.4).
 *
 * x = counted (hit-or-miss) trial index, y = rolling P(hit) over the profile's
 * `windowSize`. Chance is drawn at 0.5 because "is this animal above chance"
 * is the question being asked of a two-alternative task, and a bare line
 * without it can't answer it at a glance.
 */
export function MetricChart({
  metric,
  current,
  history,
}: {
  /** The profile entry — supplies the human label and window size. */
  metric: LiveMetric | null;
  /** The latest pushed value, or null before any trial counts. */
  current: TelemetryMetric | null;
  history: number[];
}) {
  const label = metric?.label ?? current?.id ?? "";
  const value = current?.value ?? null;

  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[11px] text-static" title={label}>
          {label}
        </span>
        <span className="font-mono text-[13px] tabular-nums text-starlight">
          {value === null ? "—" : value.toFixed(2)}
        </span>
      </div>

      <svg viewBox="0 0 100 46" className="mt-1 w-full" preserveAspectRatio="none">
        {/* Chance line. */}
        <line
          x1={0}
          y1={23}
          x2={100}
          y2={23}
          stroke={LINK_STROKE}
          strokeWidth={0.5}
          strokeDasharray="2 2"
          opacity={0.35}
          vectorEffect="non-scaling-stroke"
        />
        {history.length > 1 && (
          <polyline
            points={history
              .map(
                (v, i) =>
                  `${((i / (history.length - 1)) * 100).toFixed(2)},${((1 - v) * 46).toFixed(2)}`,
              )
              .join(" ")}
            fill="none"
            stroke={NODE_ACCENT}
            strokeWidth={1.5}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      <div className="flex items-baseline justify-between font-mono text-[10px] text-static">
        <span>n={current?.n ?? 0}</span>
        {metric && <span>window {metric.windowSize}</span>}
      </div>
    </div>
  );
}
