import type { ReactNode } from "react";

/**
 * The app's axis idiom — deliberately minimal, because it is the first one.
 *
 * `MetricStrip`s sparklines are axis-less on purpose at that size, but
 * a dashboard-sized chart needs at least its extremes labelled to be readable.
 * So: min/max ticks only, no gridlines beyond the chart's own reference line,
 * and the labels live in **HTML beside the SVG** rather than inside it —
 * anything inside a `preserveAspectRatio="none"` viewBox gets stretched
 * non-uniformly, which is fine for strokes and ruinous for text.
 *
 * The footer row generalises the one the metric sparklines already use for their
 * `n=…` / `window …` line rather than inventing a second convention.
 */
export function ChartFrame({
  title,
  yTop,
  yBottom,
  xLeft,
  xRight,
  footer,
  children,
}: {
  title?: ReactNode;
  yTop?: string;
  yBottom?: string;
  xLeft?: string;
  xRight?: string;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      {title && <div className="mb-1.5 text-[11px] text-static">{title}</div>}
      <div className="flex items-stretch gap-1.5">
        {(yTop || yBottom) && (
          <div className="flex w-[26px] shrink-0 flex-col justify-between py-px text-right font-mono text-[9px] tabular-nums text-static/80">
            <span>{yTop}</span>
            <span>{yBottom}</span>
          </div>
        )}
        <div className="min-w-0 flex-1">{children}</div>
      </div>
      {(xLeft || xRight || footer) && (
        <div className="mt-1 flex items-baseline justify-between gap-2 pl-[32px] font-mono text-[9px] tabular-nums text-static/80">
          <span className="truncate">{xLeft}</span>
          {footer}
          <span className="truncate">{xRight}</span>
        </div>
      )}
    </div>
  );
}
