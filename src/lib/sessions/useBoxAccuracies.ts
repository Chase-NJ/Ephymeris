import { useMemo } from "react";

import { useSessionStore } from "./context";
import {
  EMPTY_LIVE_TRIALS,
  advance,
  rollingAccuracy,
  vocabFrom,
  vocabIsUsable,
} from "./liveTrials";
import { useStrobeVersion } from "./useLiveTrials";
import type { SessionBox, TaskProfile } from "./types";

/**
 * Pooled rolling accuracy per animal, for the constellation's star
 * temperatures (`dashboard.md` §9.2).
 *
 * Derives every box in one pass rather than mounting a hook per box: React
 * forbids hooks in a loop, and a probe component per box to work around that
 * would put render-ordering between the data and the scene for no gain.
 * Recomputing all six from their strobe logs is cheap — the logs are decoded
 * `{code, at}` pairs and the fold is linear — and it runs on the store's
 * version bump, which is already batched at the sidecar's 20 Hz.
 */
export function useBoxAccuracies(
  boxes: SessionBox[],
  window: number,
  /**
   * Sketch path → its profile, from `useTaskProfiles`. Passed in rather than
   * fetched here so the route asks the sidecar for each sketch once and both
   * the star temperatures and the metric titles read the same answer.
   */
  profiles: Record<string, TaskProfile | null | undefined>,
): Record<string, number | null> {
  const store = useSessionStore();
  const version = useStrobeVersion();

  return useMemo(() => {
    const out: Record<string, number | null> = {};
    for (const box of boxes) {
      const profile = profiles[box.sketchPath];
      const vocab = vocabFrom(profile?.strobes ?? {});
      if (!vocabIsUsable(vocab)) {
        out[box.animalId] = null;
        continue;
      }
      const derived = advance(EMPTY_LIVE_TRIALS, store.getStrobes(box.box), vocab);
      out[box.animalId] = rollingAccuracy(derived.trials, window);
    }
    return out;
    // `version` is the store's change signal; the strobe arrays it exposes are
    // mutated in place, so nothing else here would tell us they grew.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boxes, profiles, store, version, window]);
}
