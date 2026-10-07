import { useEffect, useMemo, useRef } from "react";

import type { SessionListItem } from "@/lib/analytics/types";
import { monthBins } from "@/lib/logbook/rail";

/** Height of a day's bar per session, capped — a day runs one or two. */
const BAR_UNIT = 4;
const BAR_MAX = 12;

/**
 * Every month the cohort spans, oldest to newest, each a row of per-day bars:
 * where the rail is the close-up, this is the overview. A month off is an
 * empty cell rather than a missing one. Clicking a month jumps the rail to
 * its newest session.
 */
export function MonthStrip({
  sessions,
  selectedId,
  onSelect,
}: {
  sessions: SessionListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const bins = useMemo(() => monthBins(sessions), [sessions]);
  const selectedMonth = sessions.find((s) => s.id === selectedId)?.date.slice(0, 7) ?? null;
  const strip = useRef<HTMLDivElement>(null);

  // Keep the current month in view as the rail moves through history.
  useEffect(() => {
    if (!selectedMonth) return;
    strip.current
      ?.querySelector<HTMLElement>(`[data-month="${selectedMonth}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selectedMonth]);

  if (bins.length === 0) return null;

  return (
    <div
      ref={strip}
      className="scrollbar-none flex gap-1 overflow-x-auto border-b border-halo px-3 pt-3 pb-2"
      role="group"
      aria-label="Jump to a month"
    >
      {bins.map((bin, index) => {
        const current = bin.key === selectedMonth;
        const showYear = index === 0 || bins[index - 1]!.year !== bin.year;
        return (
          <button
            key={bin.key}
            type="button"
            data-month={bin.key}
            disabled={bin.total === 0}
            onClick={() => bin.newestId && onSelect(bin.newestId)}
            aria-label={`${bin.label} ${bin.year}: ${bin.total} session${bin.total === 1 ? "" : "s"}`}
            aria-pressed={current}
            className={`flex shrink-0 flex-col items-start rounded-sm px-1.5 pt-1 pb-1 transition-colors disabled:cursor-default ${
              current ? "bg-halo/70" : "hover:bg-halo/40"
            }`}
          >
            <span className="flex h-[12px] items-end gap-px" aria-hidden>
              {bin.days.map((count, d) => (
                <span
                  key={d}
                  className={`w-[2px] ${count > 0 ? (current ? "bg-pulsar" : "bg-static") : "bg-halo"}`}
                  style={{ height: count > 0 ? Math.min(BAR_MAX, count * BAR_UNIT + 4) : 1 }}
                />
              ))}
            </span>
            <span
              className={`mt-1 font-mono text-[10px] uppercase ${
                current ? "text-starlight" : bin.total === 0 ? "text-static/50" : "text-static"
              }`}
            >
              {bin.label}
              {showYear && <span className="ml-1 text-static/70">{String(bin.year).slice(2)}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
