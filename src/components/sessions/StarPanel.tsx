import { useMemo } from "react";

import { LiveStateMachine } from "@/components/task/SketchStateMachine";
import { LivePanels } from "./LivePanels";
import { MetricStrip } from "./MetricStrip";
import { SpineStarPanel } from "./SpinePanel";
import { PanelFrame, Readout, type PanelProps } from "./StarPanelFrame";
import { usePortStatus } from "@/lib/hardware/context";
import { useBoxTelemetry } from "@/lib/sessions/context";
import { rollingAccuracy } from "@/lib/sessions/liveTrials";
import { useLiveTrials } from "@/lib/sessions/useLiveTrials";
import { liveScoring } from "@/lib/sessions/liveScoring";
import { metricLabels, useTaskProfile } from "@/lib/sessions/useTaskProfiles";
import type { TaskProfile } from "@/lib/sessions/types";
import { taskGraph } from "@/lib/tasks/topology";
import { useLiveNode } from "@/lib/tasks/useLiveNode";

/**
 * The zoomed-in star view (`ARCHITECTURE.md#live-session-views`).
 *
 * Docked and translucent over the still-rendering scene rather than replacing
 * it — arrival means the camera is close to that star with an instrument panel
 * open, not a cut to a different screen.
 *
 * The panel is a wide HUD now, sized so **everything is on screen at once** on
 * the lab machines: a header band (who this is, its clock, its controls, its
 * rolling accuracy), the **trial flow** — the task's own state machine with a
 * token on the state this animal is in right now — and below it the live
 * charts beside a metrics-and-strobes column. The graph answers "what is it
 * doing"; the charts answer "how is it doing"; the sidecar's own rolling
 * metrics (`MetricStrip`) ride along so opening the panel loses nothing the
 * tile showed; and the strobe feed is always visible — it is how you check
 * that the box is still talking, which matters exactly when something looks
 * wrong.
 */

/** Trials the star's temperature averages over — the same window the task's
 *  own live metrics use, so the two readouts agree. */
const ACCURACY_WINDOW = 20;

export function StarPanel(props: PanelProps) {
  const profile = useTaskProfile(props.box.sketchPath);
  // A spine task is drawn from its sidecar replay alone; the legacy panels,
  // which decode strobe names, are never mounted for one (`ARCHITECTURE.md#live-session-views`).
  return profile?.spine !== undefined ? (
    <SpineStarPanel {...props} profile={profile} />
  ) : (
    <LegacyStarPanel {...props} profile={profile} />
  );
}

function LegacyStarPanel({ profile, ...props }: PanelProps & { profile: TaskProfile | null }) {
  const { box } = props;
  const metrics = useBoxTelemetry(box.box);
  const labels = useMemo(() => metricLabels(profile), [profile]);
  const scoring = liveScoring(profile);
  const port = usePortStatus(box.box);
  const live = port.state === "IN_SESSION";

  const { state: trials, usable } = useLiveTrials(box.box, profile?.strobes);
  const model = useMemo(() => taskGraph(profile), [profile]);
  const { node: liveNode, condition: liveCondition } = useLiveNode(
    box.box,
    model,
    profile?.strobes,
  );
  /**
   * Conditions this box has actually presented so far, for the tick strip.
   *
   * `trials.odorCodes` accumulates only from trials the session has *seen*, so
   * this is the one readout on the screen that can say a declared condition has
   * not come up yet — the sparklines below enumerate observed odors and cannot.
   * That is the first-ten-minutes question.
   */
  const observedConditions = useMemo(() => {
    const names = new Set(
      trials.odorCodes.map((code) => (profile?.strobes?.[code] ?? "").toUpperCase()),
    );
    return new Set(
      model.conditions.filter((c) => names.has(c.strobeName)).map((c) => c.id),
    );
  }, [trials.odorCodes, profile, model]);
  const accuracy = useMemo(
    () => rollingAccuracy(trials.trials, ACCURACY_WINDOW),
    [trials.trials],
  );

  return (
    <PanelFrame
      {...props}
      profile={profile}
      live={live}
      readout={
        // The star's own temperature, stated in words — the constellation
        // encodes it as colour, and a colour scale nobody can read precisely
        // still needs its number somewhere.
        <Readout
          title="Rolling accuracy"
          value={accuracy}
          count={trials.trials.length}
        />
      }
      flow={
        model.usable && (
          /* The sketch viewer's state machine, live: same glyphs, same
             CSS-pixel type at every panel width, with the box's current
             state wearing the token and the caption strip narrating it. */
          <LiveStateMachine
            model={model}
            liveNode={liveNode}
            liveCondition={liveCondition}
            observedConditions={observedConditions}
          />
        )
      }
      charts={
        usable && scoring.scored ? (
          <LivePanels
            live={trials}
            strobeNames={profile?.strobes ?? {}}
            // 32, down from 36 when the trial flow was the smaller drawing:
            // the state machine above earns its extra rows out of the
            // charts' aspect so the panel still fits 1080 without scrolling.
            chartHeight={32}
          />
        ) : (
          <p className="text-[11px] leading-relaxed text-static">
            {!scoring.scored
              ? scoring.note
              : profile
              ? "This sketch's Task Profile doesn't declare the strobes the panels are derived from, so only the strobe feed is available."
              : "No Task Profile for this sketch — only the strobe feed is available."}
          </p>
        )
      }
      metrics={
        <MetricStrip box={box.box} metrics={metrics} labels={labels} note={scoring.note} bare />
      }
    />
  );
}
