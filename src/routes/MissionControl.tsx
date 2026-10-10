import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  CircleAlert,
  NotebookPen,
  Play,
  RotateCcw,
  Square,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { Button } from "@/components/common/controls";
import { CarryForwardPanel } from "@/components/logbook/CarryForwardPanel";
import { QuickNote } from "@/components/logbook/QuickNote";
import { WrapUpLog } from "@/components/logbook/WrapUpLog";
import { useBackupStatus } from "@/lib/backup/useBackupStatus";
import { RatPlacementBanner } from "@/components/sessions/RatPlacementBanner";
import { ReturnChecklist } from "@/components/sessions/ReturnChecklist";
import { SessionWrapUp } from "@/components/sessions/SessionWrapUp";
import { ElapsedClock, StateChip, clockSpan } from "@/components/sessions/BoxStatus";
import { Constellation3D } from "@/components/sessions/Constellation3D";
import { RecordingRail, ScopeButtons } from "@/components/recording/RecordingRail";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import type { ScopeTrigger } from "@/lib/intan/windows";
import { MetricStrip } from "@/components/sessions/MetricStrip";
import { StarPanel } from "@/components/sessions/StarPanel";
import { errorMessage } from "@/lib/cohorts/commands";
import { useAllPortStatuses, usePortStatus } from "@/lib/hardware/context";
import { springPanel } from "@/lib/motion";
import { useDeparture } from "@/lib/nav/departure";
import {
  abandonSession,
  boxesNeedingFlash,
  endSession,
  startAll,
  startBox,
  endGroup,
  stopBox,
} from "@/lib/sessions/commands";
import {
  useBoxEnded,
  useBoxTelemetry,
  useBoxWriteError,
  useSessionStore,
} from "@/lib/sessions/context";
import { missionControlHint, stepUrl } from "@/lib/sessions/flow";
import type { SessionBox } from "@/lib/sessions/types";
import { useBoxAccuracies } from "@/lib/sessions/useBoxAccuracies";
import { useSessionFlow } from "@/lib/sessions/useSessionFlow";
import { metricLabels, useTaskProfiles } from "@/lib/sessions/useTaskProfiles";
import { useLastRuns } from "@/lib/analytics/useLastRuns";
import { resolveFlag } from "@/lib/logbook/commands";
import { useLogbook, useLogbookStore } from "@/lib/logbook/context";
import type { NoteScope } from "@/lib/logbook/types";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Mission Control (`ARCHITECTURE.md#running-boxes`).
 *
 * The 3D constellation is the centerpiece (`ARCHITECTURE.md#one-sky`), so it is the whole view: a
 * full-bleed sky with the chrome in two HUD rails over it, the same stage the
 * Dashboard is. The cards used to sit in a grid
 * *below* the sky, which meant six boxes pushed the constellation off the top of
 * the screen — the one thing this view exists to show, scrolled away by the
 * boxes it is showing. Now nothing scrolls but the rails themselves.
 *
 * Left rail: what this session is, and the three things you can do to it whole.
 * Right rail: one tile per box, which the focused star's panel swaps in for.
 * The tiles still exist alongside the stars because an unlit star is
 * deliberately inert — Start for a box that isn't running has to be reachable
 * somewhere — and the panel's controls are the same actions, just reachable
 * from the panel too.
 */

/** Trials the star temperatures average over — matches `StarPanel`'s readout
 *  and the task profiles' own live-metric window, so they never disagree. */
const ACCURACY_WINDOW = 20;

/** The right rail's resting width — six tiles' worth. Mirrored in the left
 *  rail's literal `w-[392px]` and the centre stage's `left-[392px]`. */
const RAIL_WIDTH = 392;
/**
 * The rail's width while a star's panel is open. Wide enough that the panel
 * shows the graph, charts, metrics and strobe feed without scrolling at the
 * lab machines' 1920×1080; the camera's `frameShift` below keeps the focused
 * star visible in the strip the chrome leaves.
 */
const RAIL_WIDTH_FOCUSED = 824;
/** The sidebar's width in px — keep in sync with `--spacing-sidebar`. */
const SIDEBAR_PX = 200;
/**
 * Where the focused star sits, in px left of centre: half the difference
 * between the right-docked chrome (the focused rail) and the left chrome
 * (sidebar + left rail), so the star lands centred in the visible strip
 * between them (`SceneIntent.frameShift`).
 */
const PANEL_FRAME_SHIFT = (RAIL_WIDTH_FOCUSED - (SIDEBAR_PX + RAIL_WIDTH)) / 2;

export function MissionControl() {
  const { id: sessionId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const sessionStore = useSessionStore();

  const [actionError, setActionError] = useState<string | null>(null);
  /** Boxes the last start was refused for, unflashed (`ARCHITECTURE.md#what-a-board-carries`). */
  const [needFlash, setNeedFlash] = useState<number[] | null>(null);
  const [busy, setBusy] = useState(false);

  const connected = status === "connected";

  const { session, cohortId, cohort, rigGroupId, boxes, flow, error: loadError, refresh } =
    useSessionFlow(sessionId);
  const error = actionError ?? loadError;
  const {
    hasRun,
    // Switch Group (`ARCHITECTURE.md#group-step`) is only meaningful with more than one populated group.
    multiGroup,
    // Also an Intan recording (`RECORDING.md`). Everything it adds to this screen
    // is an ADDITION — the rail block and each box's scope buttons — and renders
    // nothing for a behavior-only session.
    isRecording,
    group: groupInfo,
    lastGroup,
    neverConfirmed,
    name: sessionName,
  } = flow;
  const groupDone = flow.progress.done;

  // The session log (`DATA.md#the-session-log`): the quick note, this cohort's
  // open carry-forward flags, and the wrap-up's operator and summary.
  const logStore = useLogbookStore();
  const logEntry = useLogbook(cohortId);
  useEffect(() => {
    if (connected && cohortId) void logStore.load(cohortId);
  }, [connected, cohortId, logStore]);
  const roster = useMemo(
    () => (cohort?.animals ?? []).map((a) => ({ id: a.id, name: a.name, box: a.boxNumber })),
    [cohort],
  );
  const animalNames = useMemo(() => new Map(roster.map((a) => [a.id, a.name])), [roster]);
  const noteBoxes = useMemo(
    () => [...new Set(boxes.map((b) => b.box))].sort((a, b) => a - b),
    [boxes],
  );
  const [note, setNote] = useState<{ open: boolean; scope?: NoteScope | undefined }>({
    open: false,
  });
  const openNote = useCallback(
    (scope?: NoteScope) => setNote({ open: true, scope }),
    [],
  );

  // Every animal in the cohort gets a star; only those whose box is
  // actually IN_SESSION are lit and interactive. An animal in a group that
  // isn't running, or with no box at all, is present but inert.
  const portStates = useAllPortStatuses();
  // A lit star's colour is its temperature, and its temperature is this
  // animal's pooled rolling accuracy (`ARCHITECTURE.md#live-session-views`) — so the overview answers "who is
  // doing well" without opening a panel.
  // One fetch per distinct sketch, read by two things that must agree: the
  // star temperatures below, and the titles on every box's metric strip.
  const sketchPaths = useMemo(() => boxes.map((b) => b.sketchPath), [boxes]);
  const profiles = useTaskProfiles(sketchPaths);
  const accuracies = useBoxAccuracies(boxes, ACCURACY_WINDOW, profiles);
  const labelsFor = useMemo(() => {
    const out: Record<string, Record<string, string>> = {};
    for (const path of new Set(sketchPaths)) out[path] = metricLabels(profiles[path]);
    return out;
  }, [sketchPaths, profiles]);
  // Each sketch's strobe vocabulary, as the events a PSTH can be aligned to. It
  // travels to the pop-up in its URL: a scope window shares no memory with this
  // one and has no profile to look the names up in.
  const triggersFor = useMemo(() => {
    const out: Record<string, ScopeTrigger[]> = {};
    for (const path of new Set(sketchPaths)) {
      out[path] = Object.entries(profiles[path]?.strobes ?? {})
        .map(([code, name]) => ({ code: Number(code), name }))
        .filter((t) => Number.isFinite(t.code))
        .sort((a, b) => a.code - b.code);
    }
    return out;
  }, [sketchPaths, profiles]);
  // Recorded history, for the cage-ships' "most recently ran" anchor — reads
  // through the shared analytics cache, so it costs nothing once Analytics or
  // the rig view has looked at this cohort.
  const cohortIds = useMemo(() => (cohortId ? [cohortId] : []), [cohortId]);
  const lastRuns = useLastRuns(cohortIds);
  const constellationAnimals = useMemo(() => {
    const boxOf = new Map(boxes.map((b) => [b.animalId, b.box]));
    return (cohort?.animals ?? []).map((animal) => {
      const box = boxOf.get(animal.id);
      const lastRun = lastRuns.get(animal.id);
      return {
        animalId: animal.id,
        name: animal.name,
        lit: box !== undefined && portStates[box]?.state === "IN_SESSION",
        accuracy: accuracies[animal.id] ?? null,
        box: box ?? null,
        cage: animal.cage,
        lastRunAt: lastRun?.at ?? null,
        lastRunBox: lastRun?.box ?? null,
      };
    });
  }, [cohort, boxes, portStates, accuracies, lastRuns]);

  const [focusedId, setFocusedId] = useState<string | null>(null);
  const focusedBox = boxes.find((b) => b.animalId === focusedId) ?? null;

  /*
   * **Leaving flies out first** (`lib/nav/departure.ts`).
   *
   * Clearing the focus in the same commit as the navigation starts the eased
   * move while this page is still on screen, so leaving a star reads as flying
   * out of it rather than as arriving somewhere else already pulled back. The
   * camera is permanent (`constellation3d/CameraRig.tsx`), so that move simply
   * carries on across the route change — there is nothing to hand over.
   *
   * Shared by the sidebar and by this view's own Dashboard button below, so the
   * two doors out agree.
   */
  const flyOut = useCallback(() => setFocusedId(null), []);
  useDeparture(flyOut);

  // --- guided-flow state ---------------------------------------------------

  const journeyStep = groupDone && lastGroup ? ("finish" as const) : ("run" as const);

  /*
   * The way back out (`USER-GUIDE.md#switching-groups`): which boxes have had their animal carried
   * home, ticked by the operator. Kept per group — a new group's animals are
   * new animals — and "All animals are out" is the one-press answer for the
   * operator who emptied the rig before looking at the screen.
   */
  const [returned, setReturned] = useState<Set<number>>(() => new Set());
  const [wrapDismissed, setWrapDismissed] = useState(false);
  const groupKey = rigGroupId;
  useEffect(() => {
    setReturned(new Set());
    setWrapDismissed(false);
  }, [groupKey]);
  const toggleReturned = useCallback((box: number) => {
    setReturned((prev) => {
      const next = new Set(prev);
      if (next.has(box)) next.delete(box);
      else next.add(box);
      return next;
    });
  }, []);
  const allReturned = useCallback(
    () => setReturned(new Set(boxes.map((b) => b.box))),
    [boxes],
  );
  const everyoneOut = boxes.length > 0 && boxes.every((b) => returned.has(b.box));

  // The wrap-up is dismissable — "Not yet" puts the rails back — but comes
  // back for the next group, and for the same group only if a box restarts and
  // finishes again (`groupDone` flips false and true).
  useEffect(() => {
    if (!groupDone) setWrapDismissed(false);
  }, [groupDone]);
  const wrapOpen = connected && flow.wrapUpDue && !wrapDismissed;

  // N takes a note from anywhere on the screen — hands are often full, and the
  // moment is the point. Not while typing, and not over the wrap-up, which has
  // its own note box.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "n" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) {
        return;
      }
      if (note.open || wrapOpen || !session) return;
      event.preventDefault();
      openNote();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [note.open, wrapOpen, session, openNote]);

  // Whole-session elapsed, for the wrap-up's fact line only — the header has
  // its own ticking clock. Both count from the session clock
  // (`DATA.md#the-session-clock`): the first group's start, never the record's.
  const sessionSeconds = session?.clockStartedAt
    ? Math.max(0, Math.floor((Date.now() - new Date(session.clockStartedAt).getTime()) / 1000))
    : 0;
  const wrapFacts = [
    `${boxes.length} animal${boxes.length === 1 ? "" : "s"}`,
    groupInfo ? `${groupInfo.ran}/${groupInfo.count} groups` : "1 group",
    `${clockSpan(sessionSeconds)} elapsed`,
  ].join(" · ");
  const hint = missionControlHint(flow, connected);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    setNeedFlash(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setActionError(errorMessage(err));
      setNeedFlash(boxesNeedingFlash(err));
    } finally {
      setBusy(false);
    }
  }

  // Restarting a finished box begins a new run — its old stop message and
  // telemetry must not linger over the fresh one. Cleared only after the
  // start command succeeds, so a rejected start keeps the message.
  async function startOne(box: number) {
    await startBox(client, box);
    sessionStore.resetBox(box);
  }

  // Back to a choice of group for a never-confirmed session: Step 2 needs a
  // group, and the record doesn't carry one.
  function resumeSetup() {
    navigate(stepUrl.group(sessionId!));
  }

  // Shared by the left rail's End Session and the wrap-up's (`USER-GUIDE.md#ending-the-session`).
  function doEndSession() {
    void run(async () => {
      // A session that never ran is discarded, not "ended": marking it
      // completed would seed Analytics with an empty session — the same rule
      // as the session dock's Discard. Keyed on the session status, which the
      // sidecar moves to `running` on any box's start (Start All or one box
      // at a time) and which is the one thing `sessions.abandon` checks.
      if (!hasRun) {
        await abandonSession(client, sessionId!);
        navigate("/");
        return;
      }
      await endSession(client, sessionId!);
      navigate("/analytics", {
        state: {
          endedSession: sessionName,
          cohortId: session?.cohortId,
          sessionId,
        },
      });
    });
  }

  // Shared by the rail's button, the group-swap prompt (`USER-GUIDE.md#switching-groups`) and the wrap-up:
  // end this group on the rig, then choose — any group, or end the session.
  function doSwitchGroup() {
    void run(async () => {
      await endGroup(client, sessionId!);
      navigate(stepUrl.group(sessionId!));
    });
  }

  /*
   * Reloaded (or arrived from the dock) BETWEEN groups: the session is held but
   * the rig carries no group, so there is nothing here to run. The group step
   * is the next thing, not an empty cockpit.
   */
  const betweenGroups = flow.rigStep === "group";
  useEffect(() => {
    if (betweenGroups) navigate(stepUrl.group(sessionId!), { replace: true });
  }, [betweenGroups, navigate, sessionId]);

  return (
    // No `overflow-hidden`: it would clip the shared canvas back out of the
    // strip it reaches under the sidebar (`Scene.tsx`).
    <div className="relative h-full">
      {/* The sky, full-bleed and **outside the entrance animation** — the shared
          WebGL canvas lives in this element (`SharedCanvas.tsx`), so fading the
          view in would fade the constellation in with it, and the Dashboard we
          arrive from is showing the same sky. Only the chrome animates; the sky
          is handed over. Unframed for the same reason it always was: the canvas
          is transparent and fades at its edges, so it belongs to the page. */}
      <div className="absolute inset-0">
        {/*
          **Mounted at once — never on a fetch.**

          This view's scene has to claim the shared canvas (`SharedCanvas.tsx`)
          before anything else can, because until it does, the canvas is still
          owned by the view we just left and still rendering *that* camera. Wait
          on `getCohort` and `sessions.status` first and you get exactly that:
          the previous page's sky — its camera, its star colours — held on
          screen for the length of two round trips, then the whole sky cutting
          over at once the moment this scene finally mounts. It reads as a
          camera jump and it is really a late handoff.

          Rendering immediately is safe because the *asterism* comes from
          settings, not from either fetch: with no animals yet the constellation
          draws its unoccupied stars at exactly the positions the occupied ones
          will use, so animals arriving later light up slots rather than moving
          anything. The cohort id only keys the animals' ships, so it can be
          empty while there are none.
        */}
        <Constellation3D
          cohortId={cohortId ?? ""}
          animals={constellationAnimals}
          focusedId={focusedId}
          onFocus={setFocusedId}
          frameShift={PANEL_FRAME_SHIFT}
        />
      </div>

      {/* The chrome, over the sky in two rails (the
          Dashboard's layout). Both rails ignore the pointer so the sky between
          the tiles still orbits; the tiles themselves take it back. */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        // Owns its own exit: this is a sky route, so the shell holds the page
        // opaque on the way out and anything that should fade has to say so
        // (`AppShell`). Without it the rails sit fully opaque over the incoming
        // page for the length of the transition.
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="pointer-events-none absolute inset-0"
      >
        {/* The session column: what this session IS, and the three things you
            can do to it as a whole. The title rides inside the rail (p-4 + pt-3
            = the shared 28px title line, pl-8 = the shared 32px indent). */}
        <div className="scrollbar-none pointer-events-none absolute inset-y-0 left-0 w-[392px] overflow-y-auto p-4 pl-8">
          <div className="pointer-events-auto flex flex-col gap-3 pt-3">
            {/* The way out. Mission Control is reached from the Dashboard's
                hero CTA but had no route back short of the sidebar, which reads
                as abandoning the run — so the one control that says otherwise
                belongs here, in the rail that owns the session as a whole.
                **Leaving does not stop anything**: the runner is sidecar-side
                and telemetry keeps accumulating (`SessionsProvider` is mounted
                at the app root for exactly this), and the Dashboard's session
                dock is the way back in. The title says so, because "back" on a
                running session is otherwise a fair thing to hesitate over. */}
            <span className="self-start">
              <Button
                variant="ghost"
                title="The session keeps running — pick it up again from the Dashboard"
                // Clears the focus on the way out for the same reason the
                // sidebar does — one commit, so the fly-out is still in the air
                // when the Dashboard's rig claims the camera.
                onClick={() => {
                  flyOut();
                  navigate("/");
                }}
              >
                <ArrowLeft size={13} strokeWidth={1.75} />
                Dashboard
              </Button>
            </span>

            <Header
              name={sessionName ?? "—"}
              date={session?.date ?? ""}
              // The session clock (`DATA.md#the-session-clock`): the first
              // group's start, the same moment the log's T+ offsets count
              // from. Gated on the session having run — until then, "started
              // 11:49" with a ticking counter describes a run that never began.
              startedAt={hasRun ? (session?.clockStartedAt ?? null) : null}
              groupName={groupInfo?.name ?? null}
            />

            <SessionJourney
              step={journeyStep}
              hint={hint}
              group={groupInfo}
              compact
              recording={isRecording}
            />

            {error && (
              <div
                className="flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
                style={{ color: "var(--color-status-error)" }}
              >
                <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
                {error}
              </div>
            )}
            {/* A start refused because a board doesn't carry its mapped sketch
                (`ARCHITECTURE.md#what-a-board-carries`). Mission Control is
                where set-up ends, so nothing else leads back to the step that
                flashes. Not while a box runs: re-confirming there would reset
                the mapping under it. */}
            {needFlash && actionError && rigGroupId && flow.progress.running === 0 && (
              <Button
                disabled={busy || !connected}
                onClick={() => navigate(stepUrl.boxes(sessionId!, rigGroupId))}
              >
                Back to Boxes
              </Button>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {/* Gone, not greyed, once every box is already running: a disabled
                  primary button is the loudest thing in the rail and it is
                  advertising the one action that has nothing left to do. The
                  per-box Start controls remain for a box that later finishes,
                  and this returns the moment one does. */}
              {!flow.progress.allRunning && (
                <Button
                  variant="primary"
                  disabled={busy || !connected || boxes.length === 0}
                  onClick={() =>
                    void run(async () => {
                      await startAll(client, sessionId!);
                      sessionStore.resetFinishedBoxes();
                    })
                  }
                >
                  <Play size={13} strokeWidth={2} />
                  Start All
                </Button>
              )}
              {/* Only once a group is under way: "switch" implies one already
                  ran, and before that Resume setup (or Start All) is the real
                  path. */}
              {multiGroup && hasRun && (
                <Button
                  disabled={busy || !connected}
                  title="Ends this group's runs, then lets you pick which group runs next"
                  onClick={doSwitchGroup}
                >
                  <Users size={13} strokeWidth={1.75} />
                  Switch Group
                </Button>
              )}
              <Button
                variant="ghost"
                // Not before the snapshot: discard-or-end is decided on it.
                disabled={busy || !connected || !session}
                onClick={doEndSession}
              >
                {hasRun ? "End Session" : "Discard session"}
              </Button>
              <Button
                variant="outline"
                disabled={!connected || !session}
                title="Add a note to the session log (N)"
                onClick={() => openNote()}
              >
                <NotebookPen size={13} strokeWidth={1.75} />
                Note
              </Button>
            </div>

            {/* Whatever the last session asked this one to check
                (`DATA.md#carry-forward-flags`). Resolving it here records that
                it was dealt with during this session. */}
            <CarryForwardPanel
              flags={logEntry.openFlags}
              sessions={logEntry.sessions}
              names={animalNames}
              onResolve={async (note) => {
                await resolveFlag(client, note.id, true, sessionId ?? null);
              }}
            />

            {isRecording && <RecordingRail />}
          </div>
        </div>

        {/* The box column: one tile per box, or the focused star's instrument
            panel. They SWAP rather than stack — the panel is that box's tile
            opened up, and two absolutely-positioned columns fighting for one
            edge is what the panel's old self-docking amounted to. Six tiles
            scroll inside this rail; the window itself never scrolls.

            The rail itself widens while a panel is open: the panel needs the
            room for its graph, charts and metrics, the tiles don't — so the
            width belongs to the rail's state, animated on the same spring as
            the swap. Overflow stays as the graceful fallback for windows too
            short to show the whole panel. */}
        <motion.div
          initial={false}
          animate={{ width: focusedBox ? RAIL_WIDTH_FOCUSED : RAIL_WIDTH }}
          transition={springPanel}
          // The max-width caps the animated width on windows too narrow for
          // the focused rail — the panel gives up width (and falls back to
          // wrapping) before it covers the session column. 392px = the left
          // rail's literal width.
          className="scrollbar-none pointer-events-none absolute inset-y-0 right-0 max-w-[calc(100%-392px)] overflow-y-auto p-4 pr-8"
        >
          {/* `popLayout`, never `wait` — the same call `AppShell`'s route
              transition makes and for the same reason: `wait` holds the
              incoming child until the outgoing one has finished exiting, so
              anything that stalls an exit stalls the swap itself and the panel
              simply never arrives. Here the new child mounts at once and the old
              one is lifted out of flow to leave.

              **No `initial={false}`.** That suppressed the enter animation on
              the presence's first render, which is precisely the arrival from
              box mapping — so the tiles that slide in and out beautifully when a
              star is focused simply appeared on the way into the session. The
              swap grammar was already written; it was only switched off for the
              one entrance the operator sees first. */}
          <AnimatePresence mode="popLayout">
            {focusedBox ? (
              <StarPanel
                key={`panel-${focusedBox.box}`}
                box={focusedBox}
                busy={busy || !connected}
                durationMinutes={session?.durationMinutes ?? null}
                onStart={() => void run(() => startOne(focusedBox.box))}
                onStop={() => void run(() => stopBox(client, focusedBox.box))}
                onReset={() =>
                  void run(() => client.call(CMD.PORT_RESET, { box: focusedBox.box }))
                }
                onBack={() => setFocusedId(null)}
                extra={
                  <div className="mt-3 flex flex-col gap-3">
                    {/* The box's own note, scoped to it — the panel is where
                        the operator is looking when something happens there. */}
                    <span className="self-start">
                      <Button
                        variant="outline"
                        disabled={!connected || !session}
                        title={`Add a note about box ${focusedBox.box}`}
                        onClick={() =>
                          openNote({ kind: "box", animalId: null, box: focusedBox.box })
                        }
                      >
                        <NotebookPen size={13} strokeWidth={1.75} />
                        Note about box {focusedBox.box}
                      </Button>
                    </span>
                    {isRecording && (
                      <ScopeButtons
                        box={focusedBox.box}
                        animalName={focusedBox.animalName}
                        triggers={triggersFor[focusedBox.sketchPath] ?? []}
                      />
                    )}
                  </div>
                }
              />
            ) : boxes.length > 0 ? (
              <motion.div
                key="boxes"
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 12 }}
                transition={springPanel}
                className="pointer-events-auto flex flex-col gap-3 pt-3"
              >
                {boxes.map((box) => (
                  <BoxCard
                    key={box.box}
                    box={box}
                    busy={busy || !connected}
                    metricLabels={labelsFor[box.sketchPath] ?? {}}
                    triggers={isRecording ? (triggersFor[box.sketchPath] ?? []) : null}
                    durationMinutes={session?.durationMinutes ?? null}
                    onOpen={() => setFocusedId(box.animalId)}
                    onStart={() => void run(() => startOne(box.box))}
                    onStop={() => void run(() => stopBox(client, box.box))}
                    onReset={() => void run(() => client.call(CMD.PORT_RESET, { box: box.box }))}
                  />
                ))}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </motion.div>

        {/* Centre stage, between the rails: the moments that are about the
            whole rig rather than one box, and that the operator has to act on
            before anything else means much. Its right edge follows the rail's
            animated width so the group-swap prompt never underlaps an open
            panel. */}
        <motion.div
          initial={false}
          animate={{ right: focusedBox ? RAIL_WIDTH_FOCUSED : RAIL_WIDTH }}
          transition={springPanel}
          className="pointer-events-none absolute inset-y-0 left-[392px] flex items-center justify-center p-6"
        >
          <AnimatePresence mode="popLayout">
            {groupDone && !lastGroup ? (
              /* The group-swap prompt (`USER-GUIDE.md#switching-groups`): every box in this group has
                 finished and another group is waiting, so the operator's next
                 physical act is returning animals to their cages. The placement
                 scene walked backwards says so better than a sentence would. */
              <motion.div
                key="swap"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={springPanel}
                className="hud pointer-events-auto max-h-full w-full max-w-[520px] overflow-y-auto rounded-lg p-4"
              >
                <RatPlacementBanner
                  mode="return"
                  boxes={boxes.map((b) => b.box)}
                  caption="All boxes finished — return each animal to its home cage, then pick the next group."
                />
                {/* Ticked off per box, or all at once: the next group's
                    animals go into these same chambers, so "everyone is out"
                    is the fact Switch Group waits on. */}
                <div className="mt-3">
                  <ReturnChecklist
                    boxes={boxes}
                    returned={returned}
                    onToggle={toggleReturned}
                    onAll={allReturned}
                    disabled={busy || !connected}
                  />
                </div>
                <div className="mt-3 flex justify-center gap-2">
                  <Button
                    variant="primary"
                    disabled={busy || !connected || !everyoneOut}
                    onClick={doSwitchGroup}
                    {...(everyoneOut
                      ? {}
                      : { title: "Every animal needs to be out of its box first" })}
                  >
                    <Users size={13} strokeWidth={1.75} />
                    Pick next group
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={busy || !connected || !everyoneOut}
                    onClick={doEndSession}
                  >
                    End session
                  </Button>
                </div>
              </motion.div>
            ) : boxes.length === 0 ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={springPanel}
                className="hud pointer-events-auto w-full max-w-[420px] rounded-lg p-4"
              >
                {neverConfirmed ? (
                  // The hint in the left rail says what's wrong; this is the way
                  // back. Same derivation as the session dock's "Resume setup" —
                  // Step 2 needs a group and the record doesn't carry one.
                  <div className="flex flex-col items-start gap-3">
                    <p className="text-[13px] leading-relaxed text-static">
                      Boxes were never confirmed for this session, so there is
                      nothing to run yet. Pick sketches and flash from box
                      confirmation.
                    </p>
                    <Button
                      variant="primary"
                      disabled={busy || !connected}
                      onClick={resumeSetup}
                    >
                      Resume setup
                    </Button>
                  </div>
                ) : (
                  <p className="text-[13px] text-static">
                    No boxes are configured for this session yet.
                  </p>
                )}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </motion.div>
      </motion.div>

      {/* The wrap-up (`USER-GUIDE.md#ending-the-session`): the last group has run and every box has finished: the
          session is over in every sense but the record, and this says so. */}
      <SessionWrapUp
        open={wrapOpen}
        sessionName={sessionName ?? "—"}
        boxes={boxes}
        facts={wrapFacts}
        returned={returned}
        busy={busy}
        onToggle={toggleReturned}
        onAll={allReturned}
        onEnd={doEndSession}
        onAnotherGroup={multiGroup ? doSwitchGroup : undefined}
        onDismiss={() => setWrapDismissed(true)}
        log={
          session && cohortId ? (
            <WrapUpLog
              cohortId={cohortId}
              sessionId={session.id}
              sessionDate={session.date}
              roster={roster}
              boxes={noteBoxes}
            />
          ) : null
        }
      />

      {session && (
        <QuickNote
          open={note.open}
          onClose={() => setNote({ open: false })}
          sessionId={session.id}
          sessionName={sessionName ?? "—"}
          sessionDate={session.date}
          roster={roster}
          boxes={noteBoxes}
          scope={note.scope}
        />
      )}
    </div>
  );
}

/** Everything 24-hour, including the clock that keeps ticking. */
function Header({
  name,
  date,
  startedAt,
  groupName,
}: {
  name: string;
  date: string;
  startedAt: string | null;
  groupName: string | null;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Whole-session elapsed, on the session clock — a different clock than the
  // per-box ones below, which run from each box's own start.
  const sessionElapsed = startedAt
    ? Math.max(0, Math.floor((now.getTime() - new Date(startedAt).getTime()) / 1000))
    : null;

  return (
    <div className="flex flex-wrap items-baseline justify-between gap-4">
      <div>
        <h1 className="font-display text-[22px] text-starlight">{name}</h1>
        <p className="mt-1 font-mono text-[11px] text-static">
          {date}
          {startedAt && ` · started ${clock24(new Date(startedAt))}`}
          {groupName && ` · ${groupName}`}
        </p>
      </div>
      <div className="flex items-baseline gap-4">
        <BackupPill />
        <div className="text-right">
          <div className="font-mono text-[26px] tabular-nums text-starlight">
            {clock24(now)}
          </div>
          {sessionElapsed !== null && (
            <div className="mt-0.5 font-mono text-[11px] tabular-nums text-static">
              {clockSpan(sessionElapsed)} elapsed
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Mirroring state, mid-run (`DATA.md#backup-mirroring`).
 *
 * Deliberately near-silent when healthy — a session screen shouldn't spend
 * attention on something that's working. But a backup target dying during an
 * overnight run is exactly the thing you need to learn *now* rather than from
 * a log the next morning, so failure is stated in words, not a colour change.
 * Hidden entirely when no backup directory is configured: there is nothing to
 * report, and nagging about an optional setting mid-session helps no one.
 */
function BackupPill() {
  const { status } = useBackupStatus();
  if (!status.configured) return null;

  const failed = status.state === "failed";
  return (
    <span
      className="font-mono text-[11px]"
      style={{ color: failed ? "var(--color-status-error)" : "var(--color-static)" }}
      title={
        failed
          ? (status.lastError ?? "The backup directory isn't writable.")
          : `Mirroring to ${status.directory}`
      }
    >
      {failed ? "backup failing" : "backup ok"}
    </span>
  );
}

function clock24(when: Date): string {
  return when.toLocaleTimeString("en-GB", { hour12: false });
}

/**
 * One box, as a tile in the right rail.
 *
 * `.hud` rather than `.surface`: these sit over the sky now, and an opaque card
 * there would punch a hole in it (`ARCHITECTURE.md#theme`). Clicking the tile
 * flies to that box's star and opens its panel — the rail swaps to it, so the
 * tile and the panel are one object at two sizes rather than two places the
 * same controls live.
 */
function BoxCard({
  box,
  busy,
  metricLabels,
  triggers,
  durationMinutes,
  onOpen,
  onStart,
  onStop,
  onReset,
}: {
  box: SessionBox;
  busy: boolean;
  /** `liveMetrics` id → the profile's title for it — the tile's metric strip
   *  shows the condition's name rather than the slot number telemetry sends.
   *  Empty until the profile arrives, or when the sketch has none. */
  metricLabels: Record<string, string>;
  /** This box's strobe vocabulary, for its PSTH — null when the session is not
   *  a recording, which is also what hides the scope buttons. */
  triggers: ScopeTrigger[] | null;
  durationMinutes: number | null;
  onOpen: () => void;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
}) {
  const port = usePortStatus(box.box);
  const metrics = useBoxTelemetry(box.box);
  const ended = useBoxEnded(box.box);
  const writeError = useBoxWriteError(box.box);
  const live = port.state === "IN_SESSION";

  return (
    <section className="hud rounded-md p-3.5">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={onOpen}
          className="min-w-0 text-left"
          title="Open this box's panel"
        >
          <div className="truncate text-[13px] font-medium text-starlight">
            Box {box.box} · {box.animalName}
          </div>
          <div className="truncate font-mono text-[11px] text-static">
            {box.sketchName}
          </div>
          <ElapsedClock
            startedAt={box.startedAt}
            live={live}
            durationMinutes={durationMinutes}
          />
        </button>
        <StateChip state={port.state} reason={port.reason} />
      </div>

      {/* Stop (`ARCHITECTURE.md#running-boxes`) is a request the firmware honours at a trial boundary, so
          it stays available while the box is live and doesn't force a state. */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
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

      {writeError && (
        <p
          className="mt-3 text-[11px]"
          style={{ color: "var(--color-status-error)" }}
          role="alert"
        >
          {writeError}
        </p>
      )}
      {ended ? (
        <p className="mt-3 text-[11px] text-static">
          Finished — <span className="text-starlight">{ended.stopReason}</span>
        </p>
      ) : (
        <MetricStrip box={box.box} metrics={metrics} labels={metricLabels} />
      )}
      {triggers && <ScopeButtons box={box.box} animalName={box.animalName} triggers={triggers} />}
    </section>
  );
}

// `ElapsedClock`, `clockSpan` and `StateChip` moved to
// `components/sessions/BoxStatus.tsx` so `StarPanel` shows the same clock and
// chip the tile does — the two are one object at two sizes.
