import { LivePanels } from "@/features/sessions/LivePanels";
import { clockLabel, type Water } from "./playback";
import { rollingAccuracy, type LiveTrials } from "@/features/sessions/liveTrials";
import type { TaskProfile, TaskSimulation, TelemetryMetric } from "@/lib/ws/protocol";

/** As Mission Control's readout: the window rolling accuracy is taken over. */
const ACCURACY_WINDOW = 20;

const ENDED_BY: Record<TaskSimulation["endedBy"], string> = {
  trials: "reached its trial cap",
  timeLimit: "was stopped at its time limit",
  cutOff: "was cut off: it ran half an hour past its limit without reaching a trial boundary",
};

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="surface-inset rounded-sm px-2.5 py-2">
      <div className="text-[10px] text-static">{label}</div>
      <div className="font-mono text-[16px] tabular-nums text-starlight">{value}</div>
      {note && <div className="font-mono text-[10px] tabular-nums text-static/80">{note}</div>}
    </div>
  );
}

/**
 * How the animal is doing at the playhead, in the numbers a running box shows:
 * the task's live metrics as the sidecar's scorer had them at that strobe, and
 * the response, outcome and hold charts. At the session's end, the summary
 * Analytics would give the run.
 */
export function Performance({
  profile,
  live,
  metrics,
  water,
  simulation,
  ended,
}: {
  profile: TaskProfile;
  live: LiveTrials;
  metrics: readonly TelemetryMetric[];
  water: Water;
  simulation: TaskSimulation;
  ended: boolean;
}) {
  const accuracy = rollingAccuracy(live.trials, ACCURACY_WINDOW);
  const labels = new Map(profile.liveMetrics.map((metric) => [metric.id, metric.label]));
  const overall = simulation.summary.overall;
  const outcomes = simulation.summary.outcomes;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-2">
        <Tile
          label="Rolling accuracy"
          value={accuracy === null ? "—" : accuracy.toFixed(2)}
          note={`last ${Math.min(ACCURACY_WINDOW, live.trials.length)}`}
        />
        <Tile label="Trials answered" value={String(live.trials.length)} />
        <Tile label="Rewards" value={String(water.rewards)} />
        <Tile label="Water" value={`${(water.ms / 1000).toFixed(1)} s`} note="lines open" />
      </div>

      {metrics.length > 0 && (
        <table className="w-full border-collapse font-mono text-[11px] tabular-nums">
          <tbody>
            {metrics.map((metric) => (
              <tr key={metric.id} className="border-t border-halo/50">
                <td className="max-w-0 truncate py-1 pr-2 font-sans text-static" title={labels.get(metric.id)}>
                  {labels.get(metric.id) ?? metric.id}
                </td>
                <td className="w-12 py-1 text-right text-starlight">
                  {metric.value === null ? "—" : metric.value.toFixed(2)}
                </td>
                <td className="w-14 py-1 text-right text-static">n={metric.n}</td>
                <td className="w-20 py-1 text-right text-static/80">
                  {metric.hits}/{metric.counted}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <LivePanels live={live} strobeNames={profile.strobes} chartHeight={36} />

      {ended && (
        <div className="border-t border-halo/60 pt-2 text-[11px] leading-relaxed text-static">
          <span className="text-starlight">The session {ENDED_BY[simulation.endedBy]}</span> after{" "}
          {clockLabel(simulation.durationMs)}.
          {overall && overall.pSession !== null && (
            <>
              {" "}
              Overall accuracy <span className="font-mono text-starlight">{overall.pSession.toFixed(2)}</span> over{" "}
              {overall.counted} counted trials.
            </>
          )}
          {outcomes && (
            <>
              {" "}
              {outcomes.rewarded} rewarded, {outcomes.wrongWell} wrong well, {outcomes.holdFailed} hold failed,{" "}
              {outcomes.noResponse} unanswered, {outcomes.aborted} aborted.
            </>
          )}
        </div>
      )}
    </div>
  );
}
