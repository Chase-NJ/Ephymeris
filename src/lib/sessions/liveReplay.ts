import type { LiveReplay, TelemetryMetric } from "@/lib/ws/protocol";

/**
 * What a spine run's live replay (`session.replay`) puts on Mission Control's
 * readouts (`ARCHITECTURE.md#live-session-views`).
 *
 * The sidecar replays the run as it arrives and sends where the board is and
 * the numbers so far; these functions only shape that payload for the strip,
 * the caption and the star. Nothing is computed from strobes here, and no
 * figure is invented when the payload has none: a diverged run has no numbers,
 * and says why, and so does a run whose live scorer is down.
 *
 * Pure.
 */

/**
 * The run's P(correct | row) and pooled P(correct), as the metric strip draws
 * them: each with its n (counted trials) and its 95% Wilson interval
 * (`ANALYTICS.md#uncertainty`), which travel with every number.
 */
export function replayStrip(replay: LiveReplay | null): {
  metrics: TelemetryMetric[];
  labels: Record<string, string>;
  intervals: Record<string, [number, number]>;
} {
  const summaries =
    replay && replay.unavailable === null
      ? [...replay.metrics, ...(replay.overall ? [replay.overall] : [])]
      : [];
  const intervals: Record<string, [number, number]> = {};
  for (const m of summaries) {
    if (m.wilsonLow !== null && m.wilsonHigh !== null) intervals[m.id] = [m.wilsonLow, m.wilsonHigh];
  }
  return {
    metrics: summaries.map((m) => ({ id: m.id, value: m.pSession, n: m.counted })),
    labels: Object.fromEntries(summaries.map((m) => [m.id, m.label])),
    intervals,
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
    case "unavailable":
      return `Live replay unavailable — ${replay.detail ?? "it missed a strobe"}. The run is recorded as ever.`;
    default:
      break;
  }
  if (replay.unavailable !== null) {
    return `Live numbers unavailable — ${replay.unavailable}. The run is recorded and Analytics scores it.`;
  }
  return replay.status === "ended"
    ? "The run ended with no complete trial."
    : "No complete trial yet — P(correct | row) appears after the first.";
}

/** True when what is on screen is not a run the live replay describes. */
export function replayWarns(replay: LiveReplay | null): boolean {
  return (
    replay?.status === "diverged" ||
    replay?.status === "unreplayable" ||
    replay?.status === "unavailable"
  );
}

/**
 * A spine star's temperature (`ARCHITECTURE.md#status-constellation`): the run's
 * pooled P(correct) so far, as the sidecar scored it. Null before a scored
 * trial, and for any run whose numbers are withdrawn or unavailable.
 */
export function spineAccuracy(replay: LiveReplay | null): number | null {
  if (replay === null || replayWarns(replay) || replay.unavailable !== null) return null;
  return replay.overall?.pSession ?? null;
}
