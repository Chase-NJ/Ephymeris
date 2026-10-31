import type { TaskProfile } from "./types";

/**
 * What a box's live readouts can show, read from its Task Profile alone.
 *
 * `scored` is whether the live panels and the rolling metrics have anything to
 * draw for this sketch; `note` is what the metric strip says while it has no
 * value, and what stands in for the panels when nothing is scored.
 *
 * A phase-spine task (`TASKS.md#spine-tasks`) records only channel edges and
 * structural codes, which the legacy panels cannot decode, and declares no
 * `liveMetrics`: live scoring by replay is still to come. So a profile carrying
 * a `spine` snapshot and no live metrics says so, instead of drawing an empty
 * frame. It is the profile's declaration that decides, never the sketch's
 * name: a spine profile that declares live metrics is scored like any other.
 */
export function liveScoring(profile: TaskProfile | null | undefined): {
  scored: boolean;
  note: string;
} {
  if (profile?.spine !== undefined && profile.liveMetrics.length === 0) {
    return {
      scored: false,
      note:
        "Live metrics for spine tasks are not available yet. Every strobe is still " +
        "recorded; scoring spine runs is not available in Analytics yet either.",
    };
  }
  return { scored: true, note: "No live metrics yet — they appear once trials start counting." };
}
