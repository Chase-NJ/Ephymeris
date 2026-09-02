import { motion } from "framer-motion";
import { useEffect, useMemo, useReducer, useState } from "react";
import {
  ArrowRight,
  ChartLine,
  Radio,
  Rocket,
  Users,
  Workflow,
} from "lucide-react";
import { useNavigate } from "react-router";

import {
  CardFooterLink,
  CardFooterNote,
  CardRow,
  SummaryCard,
} from "@/components/common/SummaryCard";
import {
  EntranceTile,
  RigMotif,
  TaskMotif,
} from "@/components/dashboard/EntranceTile";
import { NODE_FILL, useBoxHealth, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { SessionDock } from "@/components/sessions/SessionDock";
import { recentSessions as fetchRecentSessions } from "@/lib/analytics/commands";
import { useAnalyticsStore } from "@/lib/analytics/context";
import type { DiskSession } from "@/lib/analytics/types";
import { setRigSelection, useRigSelection } from "@/lib/constellations/viewMemory";
import { PANEL_TRAVEL, springPanel, springSnappy } from "@/lib/motion";
import { useActiveCohorts, useCohortsLoaded } from "@/lib/cohorts/context";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useRunningSession } from "@/lib/sessions/context";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Dashboard / landing view (dashboard.md §3).
 *
 * The rig's constellation is the page — the same 3D browser Debug flies, same
 * shared camera and selection (`viewMemory.ts`), so moving between the two
 * views reads as one continuous sky rather than two screens with similar
 * wallpaper. Everything else docks over it as two columns of translucent HUD
 * tiles: **command** on the left (the hero CTA, then whatever sessions are in
 * flight, directly under it — "what do I do now" in one stack) and **overview**
 * on the right: a paired row of entrance tiles (Rig, Task — the two tabs that
 * had no presence here, `EntranceTile`), then the three readouts (Cohorts,
 * Boxes, Analytics).
 *
 * Selecting a star here hands off to Debug, where the box's instrument panel
 * lives — the selection and camera ride along, so the arrival flight lands in
 * the other view mid-move. **That gesture is the only entrance to a box**,
 * which is why the Boxes tile is a readout with no header link: the sky on this
 * page already *is* the rig, so a card offering to navigate to it was a third
 * route to where the user was already standing. Its rows do what its stars do.
 * The Rig *entrance* tile is not a counterexample — it opens the wiring screen,
 * which is a different place than the rig itself.
 *
 * Data stays cheap: providers the app already holds, the app-level analytics
 * cache, and `analytics.recentSessions` (folder names only). No spinners.
 */
export function Dashboard() {
  const navigate = useNavigate();
  const { settings } = useSettings();
  const cohorts = useActiveCohorts();
  const cohortsLoaded = useCohortsLoaded();
  const health = useBoxHealth();
  const running = useRunningSession();
  const selected = useRigSelection();
  const rewardSeries = useCohortRewardSeries();
  const recent = useRecentSessions();

  const cohortCount = cohorts.length;
  const boundBindings = settings.boxes.filter((b) => b.hardwareId !== null);
  const connectedCount = boundBindings.filter(
    (b) => (health[b.box] ?? "absent") !== "absent",
  ).length;

  // §4.1: starting a session requires an existing cohort — still only an
  // *existence* check; Step 1 (`/session/new`) owns per-cohort readiness.
  const hasCohorts = cohortCount > 0;

  /*
   * **The Dashboard never renders a focused sky.** Selecting a star here
   * navigates to Debug (below), so a focused Dashboard is a state nothing in
   * this view can explain: the rig selection is module-level and survives
   * navigation (`viewMemory.ts`), so leaving Debug by any route *other* than
   * its own Back — a sidebar click to Cohorts, then back to the Dashboard —
   * used to arrive parked in a star's close-up with no panel to say why.
   *
   * Cleared on the **incoming** side rather than on Debug's unmount: route
   * transitions overlap mounts, so an outgoing view's cleanup can run after the
   * incoming view has already acted. This runs on mount, so the forward
   * handoff — where the selection is set and navigated in one commit — is
   * untouched.
   */
  useEffect(() => {
    setRigSelection(null);
  }, []);

  return (
    // No `overflow-hidden`: the shared canvas reaches left under the sidebar
    // (`Scene.tsx`) and clipping here would cut it back to the content region.
    // `main` still clips at its padding box, which includes that strip.
    <div className="relative h-full">
      {/* The sky. Bound boxes as temperature stars, cage-ships in orbit —
          DebugConstellation, verbatim, including its camera.

          **Deliberately outside the entrance animation.** The shared canvas
          lives in this element (`SharedCanvas.tsx`), so fading this view in
          would fade the sky in with it — and since Debug shows the same sky,
          navigating between the two made the constellation blink out and back
          on every arrival. Only the chrome animates; the sky holds still and is
          simply handed over, which is the whole "one continuous sky" premise. */}
      <div className="absolute inset-0">
        <DebugConstellation
          // Always null, never the store value: the clearing effect above runs
          // *after* this child's own effects, so passing the live selection
          // would leave a one-commit window in which the rig starts a flight
          // the clear then reverses.
          selected={null}
          // No panel docks here, so the focused-state restrictions don't apply
          // (`ConstellationScene`) — the sky keeps pan, zoom and its pad.
          docksPanel={false}
          onSelect={(box) => {
            setRigSelection(box);
            // The instrument panel lives in Debug; the shared camera makes
            // the handoff read as one continuous flight, not a page change.
            if (box !== null) navigate("/debug");
          }}
        />
      </div>

      {/* The chrome. A plain wrapper: the two columns animate *individually*
          now, because they are doing different jobs during a star click — the
          left one crossfades with Debug's title on the shared title grid, while
          the right one is handing its place to Debug's docked panel. The sky
          stays outside either, which is the rule this split narrows rather than
          bends. */}
      <div className="pointer-events-none absolute inset-0">
        {/* The command column: the page title, the hero CTA, and whatever
            sessions are in flight, directly below it. Both columns ignore the
            pointer so the sky between the tiles still orbits; the tiles
            themselves take it back. The title rides inside the column (p-4 +
            pt-3 = the shared 28px title line, pl-8 = the shared 32px indent)
            so the stack clears it by layout rather than a hard-coded offset.

            Opacity-only, and no `exit`: a y-offset on a full-height column
            transiently overflows the scroll container and flashes the
            scrollbar, and there is nothing on the left being replaced —
            Debug's title lands on the same grid, so a crossfade reads as a
            word being swapped. */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          // Owns its own exit: between Dashboard and Debug the route stops
          // fading the page (`AppShell`), so anything that should fade has to
          // say so. Opacity only — Debug's title lands on the same title grid,
          // so a crossfade reads as a word being swapped.
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-y-0 left-0 w-[392px] overflow-y-auto p-4 pl-8"
        >
          {/* The title keeps its grid — Debug's lands on the same line, and
              the two crossfade — so the fact line hangs under it rather than
              a chip beside it. The line is the rig in one breath: boxes on
              the bus, cohorts in the library, and whether a session is going. */}
          <div className="pb-4 pt-3">
            <h1 className="font-display text-[22px] text-starlight">Dashboard</h1>
            <RigFact
              bound={boundBindings.length}
              connected={connectedCount}
              anyFault={boundBindings.some((b) => health[b.box] === "fault")}
              cohorts={cohortCount}
              running={running !== null}
            />
          </div>
          <div className="pointer-events-auto flex flex-col gap-3">
            <LaunchButton
              running={running !== null}
              hasCohorts={hasCohorts}
              onClick={() => {
                if (running) {
                  navigate(
                    `/session/${running.session.id}/control?cohort=${running.session.cohortId}`,
                  );
                } else {
                  navigate(hasCohorts ? "/session/new" : "/cohorts");
                }
              }}
            />

            <SessionDock />
          </div>
        </motion.div>

        {/* The overview column: where everything else is, at a glance — and,
            on a star click, the thing Debug's `NodeDetail` replaces.

            So it travels the panel's distance on the panel's spring
            (`PANEL_TRAVEL`, `springPanel`, matching `NodeDetail`): it leaves
            toward the right edge as the panel arrives from it, which reads as
            one surface being swapped rather than one blinking out and another
            appearing. Horizontal is safe where vertical isn't — `main` sets
            `overflow-x: hidden` explicitly, which is why the no-y rule above
            doesn't apply here.

            The exit travel is gated on a selection actually being in flight.
            Leaving the Dashboard *forward* into the guided flow moves the whole
            page −26px, and a column drifting +24px against that would read as
            stuck rather than as a handoff. */}
        <motion.div
          initial={{ opacity: 0, x: PANEL_TRAVEL }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: selected !== null ? PANEL_TRAVEL : 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-y-0 right-0 w-[392px] overflow-y-auto p-4 pl-0"
        >
          <div className="pointer-events-auto flex flex-col gap-3">
            {/* The two tabs that had no presence here — the rig's wiring and
                the task — as a paired row of doors above the readouts. They are
                compact and side by side precisely so they don't read as two
                more cards to scan: one glance says "these are places to go",
                and the column's three readouts follow underneath. */}
            <div className="grid grid-cols-2 gap-3">
              <EntranceTile
                icon={Radio}
                label="Rig"
                caption="Which board is box 3?"
                status={
                  boundBindings.length === 0
                    ? "nothing bound"
                    : `${boundBindings.length} box${boundBindings.length === 1 ? "" : "es"} bound`
                }
                motif={<RigMotif />}
                onOpen={() => navigate("/config")}
              />
              {/* No footer shortcut any more: /task opens straight into the
                  sketch viewer, so a "Sketches" link would be a second door
                  into the same room. */}
              <EntranceTile
                icon={Workflow}
                label="Task"
                caption="What the animal does — this rig's tasks"
                motif={<TaskMotif />}
                onOpen={() => navigate("/task")}
              />
            </div>

            <SummaryCard
              icon={Users}
              label="Cohorts"
              status={`${cohortCount} active`}
              onOpen={() => navigate("/cohorts")}
              empty={
                cohortsLoaded && cohortCount === 0
                  ? "No cohorts yet — create one to start recording sessions."
                  : null
              }
            >
              {cohorts.slice(0, MAX_ROWS).map((cohort) => (
                <CardRow key={cohort.id} onClick={() => navigate(`/cohorts/${cohort.id}`)}>
                  {/* The cohort's world, as the browser draws it — a row is
                      recognised by its planet before its name is read. */}
                  <PlanetDisc cohortId={cohort.id} appearance={cohort.appearance} size={16} />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                    {cohort.name}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] text-static">
                    {cohort.animalCount} animal{cohort.animalCount === 1 ? "" : "s"} ·{" "}
                    {cohort.groupCount} group{cohort.groupCount === 1 ? "" : "s"}
                  </span>
                </CardRow>
              ))}
              {cohortCount > MAX_ROWS && (
                <CardFooterLink onClick={() => navigate("/cohorts")}>
                  all {cohortCount} cohorts
                </CardFooterLink>
              )}
            </SummaryCard>

            {/* The boxes, as a readout rather than a destination. The sky on
                this page *is* the rig, and selecting a box — by clicking its
                star or one of these rows — is what opens its instrument panel;
                a header that also navigated to "Debug Mode" was offering a
                third route to a place the page already was. So the header
                states health and nothing more, and the rows carry the one real
                gesture.

                **Called Boxes, not Rig.** It was Rig until the Config tab took
                that name, at which point the column would have carried two
                tiles labelled Rig — one a door to the wiring screen, one a
                readout that deliberately goes nowhere. Boxes is also just what
                it is: the status counts boxes and every row is one. */}
            <SummaryCard
              icon={Radio}
              label="Boxes"
              status={
                <BoxesStatus
                  bound={boundBindings.map((b) => b.box)}
                  health={health}
                  connected={connectedCount}
                />
              }
              empty={
                boundBindings.length === 0
                  ? "No boxes bound yet — the Rig tab binds each one to a board."
                  : null
              }
            >
              {boundBindings.map((binding) => {
                const state = health[binding.box] ?? "absent";
                return (
                  <CardRow
                    key={binding.box}
                    // Exactly what clicking the box's star does, from a list —
                    // the selection is the rig's (`viewMemory.ts`), so the
                    // camera flies to it and Debug's panel opens on arrival.
                    onClick={() => {
                      setRigSelection(binding.box);
                      navigate("/debug");
                    }}
                  >
                    <span
                      aria-hidden
                      className="size-[7px] shrink-0 rounded-full"
                      style={{ background: NODE_FILL[state] }}
                    />
                    <span className="shrink-0 font-mono text-[11px] text-static">
                      Box {binding.box}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                      {binding.label || `Box ${binding.box}`}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-static">
                      {HEALTH_LABEL[state]}
                    </span>
                  </CardRow>
                );
              })}
              {/* The one thing an unbound rig needs, and the one thing that
                  isn't reachable by clicking the sky. Kept even though the Rig
                  tile above now offers the same destination: this line appears
                  exactly when the reader has just been told there are no boxes,
                  which is the moment the route matters most. */}
              {boundBindings.length === 0 && (
                <CardFooterLink onClick={() => navigate("/config")}>
                  bind boxes on the Rig tab
                </CardFooterLink>
              )}
              {/* Debug has no sidebar entry — it is this page with the camera
                  flown in, and a tab for it was a second door to a room you are
                  already standing in. But removing it also removed the only
                  standing sign that per-box consoles exist, so the gesture is
                  named here instead: one quiet line at the foot of the tile
                  whose rows perform it, rather than a callout competing with
                  the rig's health for attention. */}
              {boundBindings.length > 0 && (
                <CardFooterNote>select a box for its console</CardFooterNote>
              )}
            </SummaryCard>

            <SummaryCard
              icon={ChartLine}
              label="Analytics"
              status="reward accuracy"
              onOpen={() => navigate("/analytics")}
              empty={
                cohortsLoaded && cohortCount === 0
                  ? "Cohort accuracy will chart here once sessions are recorded."
                  : null
              }
            >
              {rewardSeries.map((cohort) => (
                <CardRow
                  key={cohort.id}
                  // A row names something specific, so clicking it opens that
                  // thing — the same arrival Analytics already handles when a
                  // session ends (§2.5), rather than the picker the reader has
                  // just answered by clicking.
                  onClick={() => navigate("/analytics", { state: { cohortId: cohort.id } })}
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                    {cohort.name}
                  </span>
                  {cohort.values.length === 0 ? (
                    <span className="shrink-0 font-mono text-[10px] text-static/60">
                      no scored sessions
                    </span>
                  ) : (
                    <>
                      <Sparkline
                        values={cohort.values}
                        title={`${cohort.name}: reward accuracy across ${cohort.values.length} session${cohort.values.length === 1 ? "" : "s"}`}
                      />
                      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-starlight">
                        {Math.round(cohort.values[cohort.values.length - 1]! * 100)}%
                      </span>
                    </>
                  )}
                </CardRow>
              ))}

              {recent.sessions.length > 0 && (
                <>
                  <p className="mt-2 border-t border-halo pt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-static">
                    Recent sessions
                  </p>
                  {recent.sessions.map((session) => (
                    <CardRow
                      key={session.folderPath}
                      // The folder, not a session id: these rows come from a
                      // walk of directory names (`analytics.recentSessions`),
                      // and one this machine hasn't indexed has no id to send.
                      // Analytics resolves it against the cohort's session list
                      // once that loads, and lands on the cohort either way.
                      onClick={() =>
                        navigate("/analytics", {
                          state: { cohortId: session.cohortId, sessionFolder: session },
                        })
                      }
                    >
                      <span className="shrink-0 font-mono text-[11px] text-static">
                        {session.date}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                        {session.prefixName} {session.sessionNumber}
                        <span className="text-static"> · {session.cohortName}</span>
                      </span>
                      {!session.recorded && (
                        <span
                          className="shrink-0 font-mono text-[10px] text-static/60"
                          title="Recorded by another Ephymeris machine — run a rescan in Analytics to index it here"
                        >
                          not indexed
                        </span>
                      )}
                    </CardRow>
                  ))}
                </>
              )}
            </SummaryCard>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

/** Rows before the cohort card defers to the full grid. */
const MAX_ROWS = 5;

/**
 * The page's fact line — the Rig and Settings tabs' mono line under the
 * title, answered with the rig's numbers. Coloured by state and nothing
 * else: the error tone the moment any bound box is in fault, Ion when every
 * bound box is on the bus, quiet static otherwise or with nothing bound.
 */
function RigFact({
  bound,
  connected,
  anyFault,
  cohorts,
  running,
}: {
  bound: number;
  connected: number;
  anyFault: boolean;
  cohorts: number;
  running: boolean;
}) {
  const boxesColour = anyFault
    ? "var(--color-status-error)"
    : bound > 0 && connected === bound
      ? "var(--color-status-ok)"
      : undefined;
  return (
    <p className="mt-0.5 font-mono text-[10px] text-static/70">
      <span style={boxesColour ? { color: boxesColour } : undefined}>
        {bound === 0 ? "no boxes bound" : `${connected}/${bound} boxes on the bus`}
      </span>
      {" · "}
      {cohorts} cohort{cohorts === 1 ? "" : "s"}
      {running && (
        <>
          {" · "}
          <span style={{ color: "var(--color-status-ok)" }}>session running</span>
        </>
      )}
    </p>
  );
}

/**
 * The Boxes tile's fact: the bound boxes as health dots, then the count — the
 * Rig tab's `BoxesFact`, so the two pages agree about every box before either
 * is read. Same `NODE_FILL` the sidebar's stars use.
 */
function BoxesStatus({
  bound,
  health,
  connected,
}: {
  bound: readonly number[];
  health: Partial<Record<number, BoxHealth>>;
  connected: number;
}) {
  if (bound.length === 0) return <span>none bound</span>;
  const states = bound.map((box) => health[box] ?? "absent");
  const colour = states.includes("fault")
    ? "var(--color-status-error)"
    : connected === bound.length
      ? "var(--color-status-ok)"
      : undefined;
  return (
    <>
      <span className="mr-1 flex items-center gap-1" aria-hidden>
        {states.map((state, i) => (
          <span
            key={bound[i]}
            className="size-1.5 rounded-full"
            style={{ background: NODE_FILL[state] }}
          />
        ))}
      </span>
      <span style={colour ? { color: colour } : undefined}>
        {connected}/{bound.length} connected
      </span>
    </>
  );
}

/** The sidebar constellation's health states, in words for the row readout. */
const HEALTH_LABEL: Record<BoxHealth, string> = {
  nominal: "active",
  idle: "connected",
  absent: "not detected",
  fault: "error",
};

/**
 * Per-cohort reward accuracy across sessions, for the Analytics tile's
 * sparklines. One point per session in date order: rewarded over administered
 * trials pooled across that session's runs — **the earned-drop rate, not
 * choice accuracy** (`data.md` §9.8): a correct choice that failed the
 * hold counts against it, which is what makes it the number the lab pays out
 * on. Sessions whose task has no reward vocabulary contribute nothing.
 *
 * Rides the app-level analytics cache and triggers the same per-cohort loads
 * the rig's star temperatures do, so the two never disagree about freshness.
 */
function useCohortRewardSeries(): Array<{ id: string; name: string; values: number[] }> {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();
  const cohorts = useActiveCohorts();

  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => store.subscribe("data", bump), [store]);

  useEffect(() => {
    if (status !== "connected") return;
    for (const cohort of cohorts) {
      void store.load(client, cohort.id).catch(() => {
        // An unreadable archive keeps its sparkline empty; the Analytics view
        // is where the error itself is surfaced.
      });
    }
  }, [client, status, store, cohorts, tick]);

  return useMemo(
    () =>
      cohorts.map((cohort) => {
        const summary = store.getSummary(cohort.id);
        if (!summary) return { id: cohort.id, name: cohort.name, values: [] };

        const bySession = new Map<string, { rewarded: number; administered: number }>();
        for (const run of summary.runs) {
          const outcomes = run.outcomes;
          if (!outcomes || outcomes.administered <= 0) continue;
          const acc = bySession.get(run.sessionId) ?? { rewarded: 0, administered: 0 };
          acc.rewarded += outcomes.rewarded;
          acc.administered += outcomes.administered;
          bySession.set(run.sessionId, acc);
        }

        // `summary.sessions` is already date-ordered oldest-first and includes
        // adopted archive sessions, so the line is the cohort's real history.
        const values: number[] = [];
        for (const session of summary.sessions) {
          const acc = bySession.get(session.id);
          if (acc && acc.administered > 0) values.push(acc.rewarded / acc.administered);
        }
        return { id: cohort.id, name: cohort.name, values };
      }),
    // `tick` stands in for the summaries' contents behind stable references.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cohorts, store, tick],
  );
}

/**
 * The N most recent session folders across the whole archive — including ones
 * another Ephymeris machine wrote (`analytics.recentSessions`, names only).
 * A session starting or ending refetches, so today's run appears without a
 * reload.
 */
function useRecentSessions(): { sessions: DiskSession[]; loaded: boolean } {
  const { client, status } = useSidecar();
  const running = useRunningSession();
  const runningId = running?.session.id ?? null;
  const [state, setState] = useState<{ sessions: DiskSession[]; loaded: boolean }>({
    sessions: [],
    loaded: false,
  });

  useEffect(() => {
    if (status !== "connected") return;
    let cancelled = false;
    fetchRecentSessions(client, 3)
      .then((sessions) => {
        if (!cancelled) setState({ sessions, loaded: true });
      })
      .catch(() => {
        if (!cancelled) setState({ sessions: [], loaded: true });
      });
    return () => {
      cancelled = true;
    };
  }, [client, status, runningId]);

  return state;
}

/** Sparkline geometry — small enough to live in a row, wide enough to read. */
const SPARK_W = 96;
const SPARK_H = 22;
const SPARK_PAD = 3;
/**
 * Domain floor. A fixed domain keeps every cohort's line comparable at a
 * glance (per-row normalization would stretch noise into drama), but a 0-based
 * floor spends most of the 16px of height on a range no real reward rate
 * occupies — so the floor sits below chance, not at zero.
 */
const SPARK_MIN = 0.2;

/**
 * One cohort's reward-accuracy line, on the shared [SPARK_MIN, 1] domain. The
 * dashed guide is chance (0.5); the dot is the latest session, whose value the
 * row prints beside it, so the number is never color-alone.
 */
function Sparkline({ values, title }: { values: number[]; title: string }) {
  const x = (i: number) =>
    values.length === 1
      ? SPARK_W / 2
      : SPARK_PAD + (i * (SPARK_W - 2 * SPARK_PAD)) / (values.length - 1);
  const y = (v: number) => {
    const t = Math.max(0, (v - SPARK_MIN) / (1 - SPARK_MIN));
    return SPARK_H - SPARK_PAD - t * (SPARK_H - 2 * SPARK_PAD);
  };
  const last = values[values.length - 1]!;

  return (
    <svg
      width={SPARK_W}
      height={SPARK_H}
      className="shrink-0"
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <line
        x1={SPARK_PAD}
        y1={y(0.5)}
        x2={SPARK_W - SPARK_PAD}
        y2={y(0.5)}
        stroke="var(--color-halo)"
        strokeWidth="1"
        strokeDasharray="2 3"
      />
      <polyline
        points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
        fill="none"
        stroke="var(--color-pulsar)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(values.length - 1)} cy={y(last)} r="2" fill="var(--color-pulsar)" />
    </svg>
  );
}

/**
 * The booster plume: exhaust particles thrown down-left, opposite the
 * Rocket glyph's 45° heading, from just behind its nozzle. Void-on-Pulsar
 * like the icon itself — the palette is matte, so the fire is drawn with
 * motion, not colour or glow (§2.2).
 */
const EXHAUST: ReadonlyArray<{
  x: number;
  y: number;
  size: number;
  throwPx: number;
  duration: number;
  delay: number;
}> = [
  { x: 4, y: 17, size: 4, throwPx: 10, duration: 0.6, delay: 0 },
  { x: 7, y: 19, size: 3, throwPx: 12, duration: 0.7, delay: 0.22 },
  { x: 2, y: 15, size: 2.5, throwPx: 9, duration: 0.55, delay: 0.42 },
];

/**
 * The hero CTA — still the page's single most prominent element (§3.3), now
 * the head of the command column at the column's shared width. Hovering lifts
 * the rocket toward its heading and lights the booster trail; the trail loop
 * stands down under reduced motion. Deliberately opaque: the one solid tile,
 * because the primary action should not dissolve into the sky behind it.
 */
function LaunchButton({
  running,
  hasCohorts,
  onClick,
}: {
  running: boolean;
  hasCohorts: boolean;
  onClick: () => void;
}) {
  const reduceMotion = useReduceMotion();

  return (
    <motion.button
      type="button"
      initial="idle"
      animate="idle"
      whileHover="hover"
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="group flex w-full items-center gap-4 rounded-lg bg-pulsar py-4 pl-5 pr-6 text-left"
    >
      <span className="relative shrink-0" aria-hidden>
        <motion.span
          variants={{ idle: { x: 0, y: 0 }, hover: { x: 2, y: -2 } }}
          transition={springSnappy}
          className="block"
        >
          <Rocket size={24} strokeWidth={1.75} className="text-void" />
        </motion.span>
        {!reduceMotion &&
          EXHAUST.map((p, i) => (
            <motion.span
              key={i}
              variants={{
                idle: { opacity: 0, x: 0, y: 0 },
                hover: {
                  opacity: [0, 0.7, 0],
                  x: [0, -p.throwPx],
                  y: [0, p.throwPx],
                  transition: {
                    duration: p.duration,
                    repeat: Infinity,
                    delay: p.delay,
                    ease: "easeOut",
                  },
                },
              }}
              className="absolute rounded-full bg-void"
              style={{ left: p.x, top: p.y, width: p.size, height: p.size }}
            />
          ))}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-display text-base font-semibold text-void">
          {running
            ? "Resume Session"
            : hasCohorts
              ? "Start a Session"
              : "Create a cohort to get started"}
        </span>
        <span className="mt-0.5 block text-[12px] text-void/70">
          {running
            ? "A session is running — jump back into Mission Control"
            : hasCohorts
              ? "Configure boxes and begin data collection"
              : "Sessions run against a cohort — you'll need one first"}
        </span>
      </span>
      <ArrowRight
        size={18}
        strokeWidth={2}
        className="shrink-0 text-void transition-transform group-hover:translate-x-0.5"
      />
    </motion.button>
  );
}
