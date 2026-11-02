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
 * `liveMetrics`. Mission Control scores it by replaying the run as it arrives
 * (`session.replay`, `liveReplay.ts`) and never asks this; Debug Mode runs no
 * replay, so a profile carrying a `spine` snapshot and no live metrics says so
 * there, instead of drawing an empty frame. It is the profile's declaration that
 * decides, never the sketch's name: a spine profile that declares live metrics
 * is scored like any other.
 */
export function liveScoring(profile: TaskProfile | null | undefined): {
  scored: boolean;
  note: string;
} {
  if (profile?.spine !== undefined && profile.liveMetrics.length === 0) {
    return {
      scored: false,
      note:
        "Spine tasks are scored live in Mission Control, by replaying the run; Debug Mode " +
        "runs no replay. Every strobe is still recorded, and Analytics scores the run.",
    };
  }
  return { scored: true, note: "No live metrics yet — they appear once trials start counting." };
}
