import type { LiveReplay, TelemetryMetric } from "@/lib/ws/protocol";

/**
 * What a spine run's live replay (`session.replay`) puts on Mission Control's
 * readouts (`ARCHITECTURE.md#live-session-views`).
 *
 * The sidecar replays the run as it arrives and sends where the board is and
 * the numbers so far; these functions only shape that payload for the strip and
 * the caption. Nothing is computed from strobes here, and no figure is invented
 * when the payload has none: a diverged run has no numbers, and says why.
 *
 * Pure.
 */

/** The run's P(correct | row) and pooled P(correct), as the metric strip draws them. */
export function replayStrip(replay: LiveReplay | null): {
  metrics: TelemetryMetric[];
  labels: Record<string, string>;
} {
  const summaries = replay ? [...replay.metrics, ...(replay.overall ? [replay.overall] : [])] : [];
  return {
    metrics: summaries.map((m) => ({ id: m.id, value: m.pSession, n: m.counted })),
    labels: Object.fromEntries(summaries.map((m) => [m.id, m.label])),
  };
}

/** What the strip says while it has no figure to show. */
export function replayNote(replay: LiveReplay | null): string {
  if (replay === null) {
    return "Scored live by replaying the run, from the board's first strobe.";
  }
  switch (replay.status) {
    case "diverged":
      return `Diverged — ${replay.detail ?? "the board did not do what replay predicts"}.`;
    case "unreplayable":
      return replay.detail ?? "Replay cannot run this run, so nothing is scored live.";
    case "ended":
      return "The run ended with no complete trial.";
    default:
      return "No complete trial yet — P(correct | row) appears after the first.";
  }
}

/** True when what is on screen is not a run that will be scored. */
export function replayWarns(replay: LiveReplay | null): boolean {
  return replay?.status === "diverged" || replay?.status === "unreplayable";
}
