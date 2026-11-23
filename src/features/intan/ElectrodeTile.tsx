import { Activity, CircleAlert } from "lucide-react";

import { HudTile } from "@/components/common/HudTile";
import { Button } from "@/components/common/controls";
import { formatOhms, measuredAgo, type ImpedanceSummary } from "./impedance";
import type { RunYieldSummary } from "./yield";

/** How many of an animal's recent runs the trend shows. */
const TREND_RUNS = 6;

/** One recorded box on the Record step: its animal's latest impedances and recent yield, judged. */
export type ElectrodeRow = {
  box: number;
  animalName: string;
  summary: ImpedanceSummary | null;
  /** Oldest first; empty when the animal has no counted run. */
  yields: RunYieldSummary[];
};

/**
 * The Record step's electrode check, per recorded box's animal:
 *
 *   - impedances (`RECORDING.md#impedance-tracking`): one button has RHX
 *     measure every site; open, shorted and changed sites are listed;
 *   - active-site yield (`RECORDING.md#active-site-yield`): how many sites
 *     were active in each of its recent runs, so a failing implant shows
 *     before the next recording rather than after it.
 *
 * Optional by design: nothing here holds up Continue.
 */
export function ElectrodeTile({
  rows,
  measuring,
  disabledReason,
  onMeasure,
}: {
  rows: readonly ElectrodeRow[];
  measuring: boolean;
  /** Why the button is off, or null when it may be pressed. */
  disabledReason: string | null;
  onMeasure: () => void;
}) {
  const now = new Date();
  const latest = rows
    .map((r) => r.summary)
    .filter((s): s is ImpedanceSummary => s !== null)
    .sort((a, b) => b.measuredAt.localeCompare(a.measuredAt))[0];
  return (
    <HudTile
      icon={Activity}
      label="Electrodes"
      status={
        latest
          ? `impedances ${measuredAgo(latest.measuredAt, now)} at ${Math.round(latest.frequencyHz)} Hz`
          : "impedances not measured"
      }
    >
      <div className="flex items-center gap-3 border-b border-halo px-4 py-3">
        <p className="flex-1 text-[11px] leading-relaxed text-static">
          RHX measures every site on every headstage, with acquisition stopped; it can take a minute.
          Each animal's values are kept, so a site is judged against its last measurement too.
        </p>
        <Button
          variant="outline"
          disabled={measuring || disabledReason !== null}
          {...(disabledReason ? { title: disabledReason } : {})}
          onClick={onMeasure}
        >
          <Activity size={13} strokeWidth={1.75} />
          {measuring ? "Measuring…" : "Measure impedances"}
        </Button>
      </div>
      <ul className="flex flex-col px-4 py-2">
        {rows.map((row) => (
          <li key={row.box} className="flex flex-col gap-0.5 py-1.5 text-[12px]">
            <div className="flex items-center gap-2.5">
              <span className="font-mono text-[11px] text-static">Box {row.box}</span>
              <span className="text-starlight">{row.animalName}</span>
              <span className="ml-auto font-mono text-[11px] text-static">
                {row.summary ? describeCounts(row.summary) : "impedances never measured"}
              </span>
            </div>
            {row.summary && <FlaggedSites summary={row.summary} />}
            <YieldTrend yields={row.yields} />
          </li>
        ))}
      </ul>
    </HudTile>
  );
}

function describeCounts(summary: ImpedanceSummary): string {
  const { counts } = summary;
  const parts = [`${counts.ok} ok`];
  if (counts.open) parts.push(`${counts.open} open`);
  if (counts.short) parts.push(`${counts.short} short`);
  if (counts.changed) parts.push(`${counts.changed} changed`);
  if (summary.missing.length) parts.push(`${summary.missing.length} not measured`);
  return parts.join(" · ");
}

function FlaggedSites({ summary }: { summary: ImpedanceSummary }) {
  const flagged = summary.sites.filter((s) => s.verdict !== "ok");
  if (flagged.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 pl-12 font-mono text-[10px]">
      {flagged.map((site) => (
        <span
          key={site.channel}
          className="flex items-center gap-1"
          style={{
            color: site.verdict === "changed" ? "var(--color-status-warning)" : "var(--color-status-error)",
          }}
        >
          <CircleAlert size={10} strokeWidth={2} />
          {site.channel} {site.verdict} {formatOhms(site.ohms)}
          {site.previousOhms !== null && (
            <span className="text-static">(was {formatOhms(site.previousOhms)})</span>
          )}
        </span>
      ))}
    </div>
  );
}

/** "active sites 12/16 · 11/16 · 9/16", oldest to newest, the newest bright. */
function YieldTrend({ yields }: { yields: readonly RunYieldSummary[] }) {
  const recent = yields.slice(-TREND_RUNS);
  if (recent.length === 0) {
    return <div className="pl-12 font-mono text-[10px] text-static">active sites: no recorded run yet</div>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 pl-12 font-mono text-[10px] text-static">
      <span>active sites</span>
      {recent.map((y, i) => {
        const newest = i === recent.length - 1;
        const notes = [
          y.startedAt ? new Date(y.startedAt).toLocaleDateString() : null,
          y.partial ? `the spike stream covered ${Math.round(y.coverage * 100)}% of the run` : null,
          y.thresholdDiffers ? "spike detection was set up differently from the latest run" : null,
        ].filter(Boolean);
        return (
          <span key={y.runId} className="flex items-center gap-1.5" title={notes.join(" · ")}>
            {i > 0 && <span aria-hidden>·</span>}
            <span
              className={newest ? "text-starlight" : ""}
              style={y.partial ? { color: "var(--color-status-warning)" } : undefined}
            >
              {y.active}/{y.total}
              {y.partial || y.thresholdDiffers ? "*" : ""}
            </span>
          </span>
        );
      })}
    </div>
  );
}
