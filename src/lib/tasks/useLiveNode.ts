import { useEffect, useMemo, useState } from "react";

import { useSessionStore } from "@/lib/sessions/context";
import { useStrobeVersion } from "@/lib/sessions/useLiveTrials";
import {
  liveConditionId,
  liveNodeId,
  type LiveCondition,
  type TaskGraphModel,
} from "./topology";

/**
 * Which state a running box is in right now, for the live task graph.
 *
 * Deliberately a scan of the raw strobe log rather than a read off
 * `useLiveTrials` — a trial *record* only exists once the trial has closed, and
 * the whole point of the live graph is to show where the animal is mid-trial.
 *
 * Only the tail is scanned. The recognised vocabulary is dense (a trial emits
 * one every few hundred milliseconds at most), so the current state is always
 * within the last handful of lines; walking a 20 000-entry log on every strobe
 * would be the one expensive thing on a screen that has to stay smooth for
 * hours.
 */
const TAIL = 24;

/**
 * A wider window for the *condition*, because it answers a different question.
 *
 * `TAIL` is tuned for "where is the token", which is always within a handful of
 * codes. "Which condition is this trial" has to reach back to the odor-on code,
 * and a correction trial with repeated pokes can push that well past 24 while
 * the trial is still running — at which point the ticks would go dark mid-trial
 * and the drawing would stop naming a condition the animal is still working on.
 * The walk stops at the trial boundary either way, so this only bounds the cost.
 */
const CONDITION_TAIL = 160;

/**
 * How long an outcome holds the token before it moves to the ITI.
 *
 * The strobes alone cannot say when a trial's delay begins, because on the
 * error paths the outcome strobe *is* the start of it: the firmware emits
 * WATER_POKE_ERROR_x or WATER_UNPOKE_EARLY_x and then goes quiet for the whole
 * errorDelay or noPokeHoldTimeout — twenty and ten seconds on the lab's
 * defaults — before END_INCORRECT_ITI closes the trial. Following the codes
 * literally therefore parked the token on "Wrong well" for twenty seconds, on a
 * box that was already counting down to the next trial.
 *
 * So the outcome gets long enough to be read and the token then advances to the
 * state the box is actually in. Long enough to register the outcome, short
 * enough to leave the delay itself legible as the ITI.
 */
const OUTCOME_SETTLE_MS = 1200;

/** Where the box is, and which condition it is there for. */
export interface LiveState {
  node: string | null;
  condition: LiveCondition;
}

export function useLiveNode(
  box: number,
  model: TaskGraphModel,
  strobes: Record<string, string> | undefined,
): LiveState {
  const store = useSessionStore();
  const version = useStrobeVersion();

  const arrived = useMemo(() => {
    if (!model.usable || !strobes) return null;
    const log = store.getStrobes(box);
    const codes = log.slice(-TAIL).map((event) => event.code);
    return liveNodeId(model, strobes, codes);
    // `version` is the render trigger: the log is mutable and its identity
    // never changes, so nothing else here would tell React it moved.
  }, [store, box, version, model, strobes]);

  const condition = useMemo(() => {
    if (!model.usable || !strobes) return null;
    const log = store.getStrobes(box);
    const codes = log.slice(-CONDITION_TAIL).map((event) => event.code);
    return liveConditionId(model, strobes, codes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, box, version, model, strobes]);

  /*
   * The one thing the strobe stream can't tell us: that nothing more is coming.
   * A timer rather than a clock read, so the switch happens on its own — during
   * a ten-second timeout there is no new strobe to re-render on, and a value
   * derived from `Date.now()` would simply never be recomputed.
   */
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    setSettled(false);
    const node = model.nodes.find((n) => n.id === arrived);
    if (!node?.settlesToIti) return;
    const timer = window.setTimeout(() => setSettled(true), OUTCOME_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [arrived, model]);

  const node = settled && model.nodes.some((n) => n.id === "iti") ? "iti" : arrived;
  return { node, condition };
}
