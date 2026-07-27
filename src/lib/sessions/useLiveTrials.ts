import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { useSessionStore } from "./context";
import {
  EMPTY_LIVE_TRIALS,
  advance,
  vocabFrom,
  vocabIsUsable,
  type LiveTrials,
  type StrobeVocab,
} from "./liveTrials";

/** Bumped whenever any box's strobe log grows — the render trigger. */
export function useStrobeVersion(): number {
  const store = useSessionStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe("strobes", cb),
    [store],
  );
  return useSyncExternalStore(subscribe, () => store.getStrobeVersion());
}

/**
 * The live trial record for one box, accumulated as strobes arrive.
 *
 * Folds only what is new on each pass and keeps compact per-trial records, so
 * a long session stays cheap and — because the source is the session store's
 * own strobe log rather than the console ring — nothing is lost when that ring
 * trims its oldest lines.
 *
 * Resets when the box or the sketch changes: a different sketch is a different
 * strobe vocabulary, and carrying trials across would mix two experiments.
 */
export function useLiveTrials(
  box: number,
  strobes: Record<string, string> | undefined,
): { state: LiveTrials; usable: boolean; vocab: StrobeVocab } {
  const store = useSessionStore();
  const version = useStrobeVersion();
  const vocab = useMemo(() => vocabFrom(strobes ?? {}), [strobes]);
  const usable = useMemo(() => vocabIsUsable(vocab), [vocab]);

  const [state, setState] = useState<LiveTrials>(EMPTY_LIVE_TRIALS);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    stateRef.current = EMPTY_LIVE_TRIALS;
    setState(EMPTY_LIVE_TRIALS);
  }, [box, vocab]);

  useEffect(() => {
    if (!usable) return;
    const log = store.getStrobes(box);
    // A log shorter than the cursor means the store was reset under us (a new
    // group, or this box restarted) — rebuild from the beginning.
    const from = log.length < stateRef.current.cursor ? EMPTY_LIVE_TRIALS : stateRef.current;
    const next = advance(from, log, vocab);
    if (next !== stateRef.current) {
      stateRef.current = next;
      setState(next);
    }
  }, [store, box, version, vocab, usable]);

  return { state, usable, vocab };
}
