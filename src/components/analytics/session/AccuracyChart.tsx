import { ChartFrame } from "@/components/charts/ChartFrame";
import type { MetricSeries } from "@/lib/analytics/types";
import { colorForIndex } from "@/lib/analytics/view";

/**
 * Each metric's accuracy over a run's counted trials, one line per metric,
 * dashed while its window is still filling. Every value is the sidecar's
 * (`MetricSeries`); the caller says what the lines score.
 */
export function AccuracyChart({
  metrics,
  label,
}: {
  metrics: MetricSeries[];
  label: string;
}) {
  return (
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
        aria-label={label}
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
  );
}
