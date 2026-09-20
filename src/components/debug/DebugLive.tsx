import { useMemo } from "react";

import { LivePanels } from "@/components/sessions/LivePanels";
import { MetricStrip } from "@/components/sessions/MetricStrip";
import { useBoxTelemetry } from "@/lib/sessions/context";
import { rollingAccuracy } from "@/lib/sessions/liveTrials";
import type { TaskProfile } from "@/lib/sessions/types";
import { useLiveTrials } from "@/lib/sessions/useLiveTrials";
import { metricLabels } from "@/lib/sessions/useTaskProfiles";

/**
 * Mission Control's live readouts, for a task started by hand in Debug Mode.
 *
 * Nothing here is a Debug Mode version of anything. It is `MetricStrip` and
 * `LivePanels` — the components `StarPanel` mounts — fed from the same two
 * sources they read there:
 *
 *  - the **trial panels** fold the session store's strobe log, which is parsed
 *    out of `port.output` for every box in every state, so it was already
 *    filling up while a console was open and simply had nowhere to be drawn;
 *  - the **rolling metrics** are the sidecar's own `MetricSet`, which used to
 *    run only inside a session and now also runs for a task armed with
 *    `port.sendStart` (`debug_run.py`), arriving as `port.telemetry` into the
 *    same per-box slot `session.telemetry` fills.
 *
 * So a number on this panel and the same number in Mission Control cannot
 * disagree: there is one scorer, one trial fold and one set of charts. The
 * difference is only what happens to the strobes afterwards — here, nothing.
 * A Debug run is not recorded and never becomes data.
 */

/** The window `StarPanel` averages over, so the two readouts agree. */
const ACCURACY_WINDOW = 20;

export function DebugLive({
  box,
  profile,
  running,
}: {
  box: number;
  profile: TaskProfile;
  /** The sidecar's word on whether the hand-started task is still going. */
  running: boolean;
}) {
  const metrics = useBoxTelemetry(box);
  const labels = useMemo(() => metricLabels(profile), [profile]);
  const { state: trials, usable } = useLiveTrials(box, profile.strobes);
  const accuracy = useMemo(
    () => rollingAccuracy(trials.trials, ACCURACY_WINDOW),
    [trials.trials],
  );

  return (
    <div className="border-t border-halo px-3 py-3">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="font-display text-[11px] font-medium tracking-wide text-static uppercase">
            Live
          </div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-static">
            {running
              ? "Scored as a session would be. Nothing here is recorded."
              : "Send START to run the task; its trials are scored here as they complete."}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[11px] text-static">Rolling accuracy</div>
          <div className="font-mono text-[16px] tabular-nums text-starlight">
            {accuracy === null ? "—" : accuracy.toFixed(2)}
          </div>
          <div className="font-mono text-[10px] tabular-nums text-static">
            {trials.trials.length > 0
              ? `${trials.trials.length} trial${trials.trials.length === 1 ? "" : "s"}`
              : "no trials yet"}
          </div>
        </div>
      </div>

      <div className="mt-3">
        <MetricStrip box={box} metrics={metrics} labels={labels} bare />
      </div>

      <div className="mt-4">
        {usable ? (
          <LivePanels live={trials} strobeNames={profile.strobes} chartHeight={36} />
        ) : (
          <p className="text-[11px] leading-relaxed text-static">
            This sketch's Task Profile doesn't declare the strobes the trial panels
            are derived from, so only the rolling metrics and the console are
            available.
          </p>
        )}
      </div>
    </div>
  );
}
