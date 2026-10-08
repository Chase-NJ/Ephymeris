import { RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { setFalseStart } from "@/lib/analytics/commands";
import { useAnalyticsStore } from "@/lib/analytics/context";
import { restartsOf } from "@/lib/analytics/session";
import type { AnalyticsSummary, RunSummary } from "@/lib/analytics/types";
import { formatDuration, wallClock } from "@/lib/logbook/clock";
import { useSidecar } from "@/lib/ws/context";

/**
 * Animals that ran more than once this session, run by run, and which of
 * those runs are set aside as false starts (`DATA.md#false-starts`).
 *
 * WHERE THE SET-ASIDE RUNS ARE LISTED. The table above holds counted runs
 * only, so a false start is named here, muted, with why — "no view may
 * silently keep whichever came last" (`DATA.md#edge-cases`) is kept by
 * showing the run that was left out, not by counting it.
 *
 * And where a person rules on one. Here rather than on the table row because
 * the runs the rule cannot judge — no profile scored them — are exactly the
 * rows the table leaves unclickable. The sidecar decides; every button is a
 * ruling sent to it, and the list redraws from its answer.
 */
export function RestartedRuns({
  summary,
  sessionId,
  names,
  interactive,
}: {
  summary: AnalyticsSummary;
  sessionId: string;
  names: Map<string, string>;
  /** False renders it read-only — the export sheet and the log. */
  interactive: boolean;
}) {
  const groups = useMemo(() => restartsOf(summary, sessionId), [summary, sessionId]);
  if (groups.length === 0) return null;
  const setAside = groups.flatMap((g) => g.runs).filter((run) => run.falseStart).length;

  return (
    <section className="mt-3 rounded-sm border border-halo/70 px-3 py-2">
      <header className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-wider text-static uppercase">
          <RotateCcw size={11} strokeWidth={1.75} />
          Restarts
        </span>
        <span className="font-mono text-[10px] text-static/70">
          {setAside === 0
            ? "every run counted"
            : `${setAside} set aside as false start${setAside === 1 ? "" : "s"} — counted nowhere`}
        </span>
      </header>
      <div className="mt-1.5 flex flex-col gap-2">
        {groups.map((group) => (
          <div key={group.animalId} className="flex flex-col gap-0.5">
            <span className="text-[11.5px] text-starlight">
              {names.get(group.animalId) ?? group.animalId}
            </span>
            {group.runs.map((run) => (
              <RunLine
                key={run.runId}
                run={run}
                cohortId={summary.cohortId}
                interactive={interactive}
              />
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function RunLine({
  run,
  cohortId,
  interactive,
}: {
  run: RunSummary;
  cohortId: string;
  interactive: boolean;
}) {
  const { client } = useSidecar();
  const store = useAnalyticsStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rule = async (value: boolean | null) => {
    setBusy(true);
    setError(null);
    try {
      await setFalseStart(client, cohortId, run.runId, value);
      await store.refreshSummary(client, cohortId);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const trials = run.outcomes?.trials ?? null;
  const overridden = run.falseStartSource === "marked" || run.falseStartSource === "restored";

  return (
    <div
      className={`grid grid-cols-[4.5rem_4.5rem_5rem_1fr_auto] items-baseline gap-x-3 pl-3 font-mono text-[10.5px] ${
        run.falseStart ? "text-static/60" : "text-static"
      }`}
    >
      <span>{wallClock(run.startedAt)}</span>
      <span>{run.durationMs === null ? "—" : formatDuration(Math.round(run.durationMs / 1000))}</span>
      <span>{trials === null ? "— trials" : `${trials} trial${trials === 1 ? "" : "s"}`}</span>
      <span className={run.falseStart ? "" : "text-starlight/80"}>{statusText(run)}</span>
      {interactive && (
        <span className="flex items-center gap-1">
          {run.falseStart ? (
            <Button variant="ghost" disabled={busy} onClick={() => void rule(false)}>
              Count it
            </Button>
          ) : (
            <Button variant="ghost" disabled={busy} onClick={() => void rule(true)}>
              Set aside
            </Button>
          )}
          {overridden && (
            <Button
              variant="ghost"
              disabled={busy}
              title="Let the false-start rule decide this run again"
              onClick={() => void rule(null)}
            >
              Use the rule
            </Button>
          )}
        </span>
      )}
      {error && <span className="col-span-5 text-status-error">{error}</span>}
    </div>
  );
}

function statusText(run: RunSummary): string {
  switch (run.falseStartSource) {
    case "automatic":
      return "false start — restarted early";
    case "marked":
      return "false start — set aside by hand";
    case "restored":
      return "counted — by hand, though the rule would set it aside";
    default:
      return "counted";
  }
}
