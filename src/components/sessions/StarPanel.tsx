import { motion } from "framer-motion";
import { ArrowLeft, Play, RotateCcw, Square } from "lucide-react";
import { useEffect, useMemo, type ReactNode, type Ref } from "react";

import { Button } from "@/components/common/controls";
import { HudPanel, HudSection } from "@/components/common/HudPanel";
import { LiveStateMachine } from "@/components/task/SketchStateMachine";
import { ElapsedClock, StateChip } from "./BoxStatus";
import { LivePanels } from "./LivePanels";
import { MetricStrip } from "./MetricStrip";
import { useBoxOutput, usePortStatus } from "@/lib/hardware/context";
import { springSnappy } from "@/lib/motion";
import { useBoxEnded, useBoxTelemetry } from "@/lib/sessions/context";
import { rollingAccuracy } from "@/lib/sessions/liveTrials";
import { useLiveTrials } from "@/lib/sessions/useLiveTrials";
import { metricLabels, useTaskProfile } from "@/lib/sessions/useTaskProfiles";
import type { SessionBox } from "@/lib/sessions/types";
import { taskGraph } from "@/lib/tasks/topology";
import { useLiveNode } from "@/lib/tasks/useLiveNode";

/**
 * The zoomed-in star view (`dashboard.md` §9.4).
 *
 * Docked and translucent over the still-rendering scene rather than replacing
 * it — arrival means the camera is close to that star with an instrument panel
 * open, not a cut to a different screen (§6.3).
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

/*
 * Layout note: this panel positions nothing. It used to dock itself to the
 * scene's right edge, which put it in the same place Mission Control's box rail
 * now lives — two absolutely-positioned things claiming one column, with only
 * z-index deciding. It is now a card in that rail's flow, so the rail owns the
 * position and the scrolling and the two swap for each other instead of
 * stacking — and the rail *widens* while this panel is open
 * (`MissionControl`'s `RAIL_WIDTH_FOCUSED`), which is where the panel's width
 * comes from.
 */
export function StarPanel({
  box,
  onStart,
  onStop,
  onReset,
  onBack,
  busy,
  durationMinutes,
  extra,
  ref,
}: {
  box: SessionBox;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
  onBack: () => void;
  busy: boolean;
  /** The session's optional time limit, for the run clock the tile also shows. */
  durationMinutes: number | null;
  /** Rendered under the header band. A recording session puts the box's scope
   *  buttons here, so the panel offers what its tile does. */
  extra?: ReactNode;
  /**
   * **Required by `AnimatePresence mode="popLayout"`, which is how this panel
   * leaves.** On exit, framer clones the child with a ref, measures the element
   * behind it, and injects a stylesheet pinning it `position: absolute` at the
   * box it just vacated. That is the whole mechanism by which an exiting child
   * stops taking up space while it animates out.
   *
   * A function component that swallows the ref reads back as `null`, framer's
   * insertion effect bails, **no pinning style is ever written**, and the panel
   * stays in the rail's normal flow for the length of its exit — shoving the
   * box tiles down the column and letting them snap up when it finally
   * unmounts. That is a silent failure: nothing errors, the exit still
   * animates, and only the layout underneath gives it away.
   *
   * So this is not decoration. Anything rendered directly inside a `popLayout`
   * presence has to be able to hold a ref — `HudPanel` forwards it through.
   */
  ref?: Ref<HTMLElement>;
}) {
  const port = usePortStatus(box.box);
  const ended = useBoxEnded(box.box);
  const metrics = useBoxTelemetry(box.box);
  const profile = useTaskProfile(box.sketchPath);
  const labels = useMemo(() => metricLabels(profile), [profile]);

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

  // Escape returns to the overview — the gesture people try first, and the
  // same rule Debug's panel follows.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onBack();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  return (
    <HudPanel ref={ref}>
      <div className="flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} title="Back to the overview (Esc)">
          <ArrowLeft size={13} strokeWidth={2} />
          Back to overview
        </Button>
        <div className="ml-auto">
          <StateChip state={port.state} reason={port.reason} />
        </div>
      </div>

      {/* The header band: identity and clock left, the box's controls in the
          middle, its temperature right — everything the tile showed, at the
          panel's width, so the swap loses nothing. */}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h2 className="font-display text-[18px] text-starlight">{box.animalName}</h2>
          <p className="font-mono text-[11px] text-static">
            Box {box.box} · {box.sketchName}
            {profile && ` · ${profile.taskName}`}
          </p>
          <ElapsedClock
            startedAt={box.startedAt}
            live={live}
            durationMinutes={durationMinutes}
          />
          {ended && (
            <p className="mt-1 text-[11px] text-static">
              Finished — <span className="text-starlight">{ended.stopReason}</span>
            </p>
          )}
        </div>

        {/* §5.3 — Stop is a request the firmware honours at a trial boundary,
            so it stays available while the box is live. */}
        <div className="flex items-center gap-2">
          <Button variant="primary" disabled={busy || live} onClick={onStart}>
            <Play size={12} strokeWidth={2} />
            Start
          </Button>
          <Button disabled={busy || !live} onClick={onStop}>
            <Square size={12} strokeWidth={2} />
            Stop
          </Button>
          <Button variant="outline" disabled={busy} onClick={onReset} title="DTR reset">
            <RotateCcw size={12} strokeWidth={2} />
            Reset
          </Button>
        </div>

        {/* The star's own temperature, stated in words — the constellation
            encodes it as colour, and a colour scale nobody can read precisely
            still needs its number somewhere. */}
        <div className="text-right">
          <div className="text-[11px] text-static">Rolling accuracy</div>
          <div className="font-mono text-[18px] tabular-nums text-starlight">
            {accuracy === null ? "—" : accuracy.toFixed(2)}
          </div>
          <div className="font-mono text-[10px] tabular-nums text-static">
            {trials.trials.length > 0
              ? `${trials.trials.length} trial${trials.trials.length === 1 ? "" : "s"}`
              : "no trials yet"}
          </div>
        </div>
      </div>

      {extra}

      {model.usable && (
        <div className="mt-3 border-t border-halo pt-3">
          <div className="mb-1 text-[11px] text-static">Trial flow</div>
          {/* The sketch viewer's state machine, live: same glyphs, same
              CSS-pixel type at every panel width, with the box's current
              state wearing the token and the caption strip narrating it. */}
          <LiveStateMachine
            model={model}
            liveNode={liveNode}
            liveCondition={liveCondition}
            observedConditions={observedConditions}
          />
        </div>
      )}

      {/* Charts left, the sidecar's own readouts right — every live number in
          one glance, no scrolling. */}
      <div className="mt-3 grid grid-cols-[minmax(0,1fr)_300px] items-start gap-4 border-t border-halo pt-3">
        <div className="min-w-0">
          {usable ? (
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
              {profile
                ? "This sketch's Task Profile doesn't declare the strobes the panels are derived from, so only the strobe feed is available."
                : "No Task Profile for this sketch — only the strobe feed is available."}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-3">
          {/* The sidecar-computed rolling metrics (`tasks.md` §5) — the same
              strip the collapsed tile shows, so focusing a star never costs
              the readout it was showing. */}
          <HudSection title="Live metrics">
            <div className="px-3 py-2.5">
              <MetricStrip box={box.box} metrics={metrics} labels={labels} bare />
            </div>
          </HudSection>

          <HudSection title="Recent strobes">
            <div className="px-3 py-2.5">
              <StrobeFeed box={box.box} strobeNames={profile?.strobes ?? {}} rows={10} />
            </div>
          </HudSection>
        </div>
      </div>
    </HudPanel>
  );
}

/** How many strobes the feed holds by default — a fixed frame, not a growing
 *  log. The panel asks for more; the frame idea is the same. */
const FEED_ROWS = 5;

const STROBE_LINE = /^(\d{1,3})\t(\d+)$/;

/** Newest row full strength, older ones receding down the frame. */
function rowOpacity(slot: number): number {
  return Math.max(0.36, 1 - slot * 0.07);
}

/**
 * The most recent strobes from this box, newest first, decoded to the
 * profile's human names (`tasks.md` §6.4); a sketch with no profile
 * gets the raw code labeled as such. Rows arrive from the top with the
 * app's snappy spring and dim as they age down the frame.
 */
function StrobeFeed({
  box,
  strobeNames,
  rows = FEED_ROWS,
}: {
  box: number;
  strobeNames: Record<string, string>;
  rows?: number;
}) {
  const lines = useBoxOutput(box);

  const recent = useMemo(() => {
    const out: Array<{ id: number; code: string; at: number }> = [];
    for (let i = lines.length - 1; i >= 0 && out.length < rows; i--) {
      const line = lines[i];
      if (!line || line.dir !== "rx") continue;
      const match = STROBE_LINE.exec(line.text);
      if (!match) continue;
      out.push({ id: line.id, code: match[1]!, at: Number(match[2]) });
    }
    return out;
  }, [lines, rows]);

  return (
    <div>
      <ul className="flex flex-col gap-1">
        {Array.from({ length: rows }, (_, slot) => {
          const strobe = recent[slot];
          if (!strobe) {
            return (
              <li
                key={`empty-${slot}`}
                className="rounded-sm border border-dashed border-halo/50 px-2 py-1.5 font-mono text-[10px] text-static/40"
                aria-hidden
              >
                —
              </li>
            );
          }
          return (
            <motion.li
              key={strobe.id}
              layout
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: rowOpacity(slot), y: 0 }}
              transition={springSnappy}
              className="flex items-center gap-2 rounded-sm border border-halo/70 bg-void/40 px-2 py-1.5"
            >
              <span className="w-8 shrink-0 rounded-sm border border-halo px-1 text-center font-mono text-[10px] text-pulsar">
                {strobe.code}
              </span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-starlight">
                {strobeNames[strobe.code] ?? `Strobe ${strobe.code}`}
              </span>
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-static">
                {formatBoardTime(strobe.at)}
              </span>
            </motion.li>
          );
        })}
      </ul>
      {recent.length === 0 && (
        <p className="mt-2 text-[11px] text-static">
          Strobes will appear here as the box reports them.
        </p>
      )}
    </div>
  );
}

/** Board `millis()` → `m:ss.t` (hours prefixed only once a run gets there). */
function formatBoardTime(ms: number): string {
  const tenths = Math.floor((ms % 1000) / 100);
  const totalSeconds = Math.floor(ms / 1000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  const mmss = `${minutes}:${String(seconds).padStart(2, "0")}.${tenths}`;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}` : mmss;
}
