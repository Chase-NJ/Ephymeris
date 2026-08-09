import type { AnalyticsSummary } from "@/lib/analytics/types";
import { ALL_SESSIONS } from "@/lib/analytics/store";

/**
 * What the numbers above rest on — cohort, how many runs actually scored, the
 * scope, and the confidence floor.
 *
 * Shared by the dashboard and the export sheet rather than living privately in
 * the route, because a figure that leaves the app needs this more than the
 * screen does: on screen the reader can go and check, and in a lab notebook
 * six months later they cannot.
 */
export function Footnote({
  summary,
  cohortName,
  scope,
}: {
  summary: AnalyticsSummary;
  cohortName: string;
  scope: string;
}) {
  const fallback = summary.runs.filter((run) => run.profileSource === "sketch-current").length;
  const inferred = summary.runs.filter((run) => run.profileSource === "inferred").length;
  return (
    <p className="px-1 font-mono text-[10px] leading-relaxed text-static/70">
      {cohortName} · {summary.counts.decoded} of {summary.counts.runs} runs scored ·{" "}
      {scope === ALL_SESSIONS ? "all sessions" : "one session"} · fewer than{" "}
      {summary.minCountedTrials} scored trials shows as a count, not a probability
      {fallback > 0 && (
        <>
          {" · "}
          <span style={{ color: "var(--color-status-warning)" }}>
            {fallback} run{fallback === 1 ? "" : "s"} decoded with the current
            task.json, which may have changed since
          </span>
        </>
      )}
      {inferred > 0 && (
        <>
          {" · "}
          <span style={{ color: "var(--color-status-warning)" }}>
            {inferred} run{inferred === 1 ? "" : "s"} scored from the recorded
            strobes alone — no task declaration survives for them
          </span>
        </>
      )}
    </p>
  );
}
