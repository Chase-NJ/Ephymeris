import { useEffect, useMemo, useState } from "react";

import { useSessionStore } from "./context";
import { getTaskProfile } from "./commands";
import {
  EMPTY_LIVE_TRIALS,
  advance,
  rollingAccuracy,
  vocabFrom,
  vocabIsUsable,
} from "./liveTrials";
import { useStrobeVersion } from "./useLiveTrials";
import type { SessionBox, TaskProfile } from "./types";
import { useSidecar } from "@/lib/ws/context";

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
): Record<string, number | null> {
  const { client } = useSidecar();
  const store = useSessionStore();
  const version = useStrobeVersion();

  // One profile per distinct sketch, not per box: a group usually runs the
  // same sketch everywhere, and this keeps it to a single fetch when it does.
  const sketchPaths = useMemo(
    () => [...new Set(boxes.map((b) => b.sketchPath))].sort(),
    [boxes],
  );
  const [profiles, setProfiles] = useState<Record<string, TaskProfile | null>>({});

  useEffect(() => {
    let active = true;
    void Promise.all(
      sketchPaths.map((path) =>
        getTaskProfile(client, path)
          .then((profile) => [path, profile] as const)
          .catch(() => [path, null] as const),
      ),
    ).then((entries) => {
      if (active) setProfiles(Object.fromEntries(entries));
    });
    return () => {
      active = false;
    };
  }, [client, sketchPaths]);

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
