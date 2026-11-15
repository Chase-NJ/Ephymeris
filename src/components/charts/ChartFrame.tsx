import type { LucideIcon } from "lucide-react";
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
 *
 * `icon` heads the title the way every HUD tile in the app heads its subject —
 * one pulsar glyph, so a page of eight panels scans by shape before it is
 * read. The glyph names the *question* (a target for accuracy, a compass for
 * strategy), never a state: status colour stays reserved for state.
 */
export function ChartFrame({
  icon: Icon,
  title,
  yTop,
  yBottom,
  xLeft,
  xRight,
  footer,
  children,
}: {
  icon?: LucideIcon;
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
      {title && (
        <div className="mb-1.5 flex items-start gap-1.5 text-[11px] text-static">
          {Icon && (
            <Icon size={13} strokeWidth={1.75} className="mt-px shrink-0 text-pulsar" />
          )}
          <div className="min-w-0 flex-1">{title}</div>
        </div>
      )}
      <div className="flex items-stretch gap-1.5">
        {(yTop || yBottom) && (
          // A ruled scale, the instrument's way: the extremes labelled, a
          // hairline spine, and a tick at each end and the midpoint.
          <div className="relative flex w-[26px] shrink-0 flex-col justify-between border-r border-static/25 py-px pr-1 text-right font-mono text-[9px] tabular-nums text-static/80">
            <span className="absolute top-0 -right-px h-px w-1 bg-static/40" aria-hidden />
            <span className="absolute top-1/2 -right-px h-px w-[3px] bg-static/30" aria-hidden />
            <span className="absolute bottom-0 -right-px h-px w-1 bg-static/40" aria-hidden />
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
