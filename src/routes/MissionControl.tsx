import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, CircleAlert, Play, RotateCcw, Square, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { useBackupStatus } from "@/lib/backup/useBackupStatus";
import { RatPlacementBanner } from "@/components/sessions/RatPlacementBanner";
import { Constellation3D } from "@/components/sessions/Constellation3D";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { MetricStrip } from "@/components/sessions/MetricStrip";
import { StarPanel } from "@/components/sessions/StarPanel";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { useAllPortStatuses, usePortStatus } from "@/lib/hardware/context";
import { springPanel } from "@/lib/motion";
import { useDeparture } from "@/lib/nav/departure";
import {
  abandonSession,
  endSession,
  sessionStatus,
  startAll,
  startBox,
  stopBox,
  switchGroup,
} from "@/lib/sessions/commands";
import {
  useBoxEnded,
  useBoxTelemetry,
  useEndedCount,
  useSessionStore,
} from "@/lib/sessions/context";
import {
  firstGroupToRun,
  populatedGroups,
  type SessionBox,
  type SessionSnapshot,
} from "@/lib/sessions/types";
import { useBoxAccuracies } from "@/lib/sessions/useBoxAccuracies";
import { useLastRuns } from "@/lib/analytics/useLastRuns";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Mission Control (`dashboard.md` §8–§6).
 *
 * The 3D constellation is the centerpiece (§6), so it is the whole view: a
 * full-bleed sky with the chrome in two HUD rails over it, the same stage the
 * Dashboard is (`dashboard.md` §2.1). The cards used to sit in a grid
 * *below* the sky, which meant six boxes pushed the constellation off the top of
 * the screen — the one thing this view exists to show, scrolled away by the
 * boxes it is showing. Now nothing scrolls but the rails themselves.
 *
 * Left rail: what this session is, and the three things you can do to it whole.
 * Right rail: one tile per box, which the focused star's panel swaps in for.
 * The tiles still exist alongside the stars because §6.2 makes an unlit star
 * deliberately inert — Start for a box that isn't running has to be reachable
 * somewhere — and §6.4 describes the panel's controls as the same actions "just
 * reachable from here too".
 */

/** Trials the star temperatures average over — matches `StarPanel`'s readout
 *  and the task profiles' own live-metric window, so they never disagree. */
const ACCURACY_WINDOW = 20;

export function MissionControl() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const cohortId = params.get("cohort") ?? "";
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const sessionStore = useSessionStore();

  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const connected = status === "connected";

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setSnapshot(await sessionStatus(client, sessionId));
  }, [client, sessionId]);

  useEffect(() => {
    if (!connected) return;
    void refresh().catch((err) => setError(errorMessage(err)));
  }, [connected, refresh]);

  useEffect(() => {
    if (!connected || !cohortId) return;
    let active = true;
    void getCohort(client, cohortId)
      .then((c) => active && setCohort(c))
      .catch((err) => active && setError(errorMessage(err)));
    return () => {
      active = false;
    };
  }, [client, connected, cohortId]);

  // §5.2 — Switch Group is only meaningful with more than one populated group.
  const multiGroup = useMemo(
    () => (cohort ? populatedGroups(cohort).length > 1 : false),
    [cohort],
  );

  const session = snapshot?.session ?? null;
  const boxes = useMemo(() => snapshot?.boxes ?? [], [snapshot]);

  /*
   * `configuring` is NOT "the mapping was never confirmed", tempting as the name
   * is. The sidecar only leaves that status in `sessions.startAll` (`app.py`), so
   * a session sits in it through confirmation, flashing, and every per-box Start
   * — the whole normal arrival at this screen. Reading it as "unconfirmed" told
   * the operator to go finish a step they had just finished, and made End
   * Session offer to *discard* runs that had actually recorded.
   *
   * So the two questions it was standing in for are asked directly, below.
   */
  const configuring = session?.status === "configuring";

  // §6.2 — every animal in the cohort gets a star; only those whose box is
  // actually IN_SESSION are lit and interactive. An animal in a group that
  // isn't running, or with no box at all, is present but inert.
  const portStates = useAllPortStatuses();
  // A lit star's colour is its temperature, and its temperature is this
  // animal's pooled rolling accuracy (§6.2) — so the overview answers "who is
  // doing well" without opening a panel.
  const accuracies = useBoxAccuracies(boxes, ACCURACY_WINDOW);
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

  const endedCount = useEndedCount();
  const runningCount = boxes.filter(
    (b) => portStates[b.box]?.state === "IN_SESSION",
  ).length;
  const allRunning = boxes.length > 0 && runningCount === boxes.length;
  const groupDone =
    boxes.length > 0 && runningCount === 0 && endedCount >= boxes.length;

  const groupInfo = useMemo(() => {
    if (!cohort || !snapshot) return null;
    const groups = populatedGroups(cohort);
    const i = groups.findIndex((g) => g.id === snapshot.groupId);
    const found = groups[i];
    if (!found || groups.length < 2) return null;
    return { index: i + 1, count: groups.length, name: found.name };
  }, [cohort, snapshot]);

  /*
   * Reached with a mapping that was never confirmed — a deep link, a reload
   * mid-setup, or Back from a partial flash. The runner holds no boxes for this
   * session, which is the fact that distinguishes it from a session that IS
   * confirmed and merely hasn't been started yet.
   */
  const neverConfirmed = configuring && boxes.length === 0;
  /*
   * Whether anything has actually recorded. The only fact discard-vs-end may
   * rest on: a session whose boxes were started one at a time never reaches
   * `running` status, and discarding it would throw away real data.
   */
  const hasRun = runningCount > 0 || endedCount > 0;

  const lastGroup = groupInfo === null || groupInfo.index === groupInfo.count;
  const journeyStep = groupDone && lastGroup ? ("finish" as const) : ("run" as const);
  const hint = !connected
    ? "Waiting for the hardware service…"
    : neverConfirmed
      ? "This session hasn't started — finish box confirmation first."
      : boxes.length === 0
        // Only name actions that exist: Switch Group is a multi-group control.
        ? multiGroup
          ? "No boxes in this group — switch group or end the session."
          : "No boxes in this group — end the session."
        : groupDone
        ? lastGroup
          ? "All boxes finished — End Session saves and wraps up."
          : "Group finished — Switch Group runs the next one."
        : runningCount > 0
          ? "Recording — Stop takes effect at the next trial boundary."
          : endedCount === 0
            ? "Animals in their boxes? Start All begins recording."
            : "Start the remaining boxes, or switch group.";

  const sessionName = session ? `${session.prefixName}_${session.sessionNumber}` : null;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
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

  // Back to Step 2 for a never-confirmed session — the same derivation the
  // session dock's "Resume setup" uses, since the record doesn't carry a group.
  function resumeSetup() {
    if (!cohort) return;
    const group = firstGroupToRun(cohort);
    if (!group) {
      setError(
        "This session's cohort no longer has a box-assigned group — end the session instead.",
      );
      return;
    }
    navigate(`/session/${sessionId}/mapping?cohort=${cohort.id}&group=${group.id}`);
  }

  // Shared by the header button and the group-swap prompt (§5.5).
  function doSwitchGroup() {
    void run(async () => {
      const next = await switchGroup(client, sessionId!);
      // No group left to run means the session is over — land on
      // Analytics, same as an explicit End Session.
      if (next === null) {
        // Carry the cohort and session so Analytics opens on the run
        // just finished rather than an empty picker (§2.5).
        navigate("/analytics", {
          state: {
            endedSession: sessionName,
            cohortId: session?.cohortId,
            sessionId,
          },
        });
        return;
      }
      navigate(`/session/${sessionId}/mapping?cohort=${cohortId}&group=${next}`);
    });
  }

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
          **Mounted on the URL's `cohortId` alone — never on a fetch.**

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
          anything.
        */}
        {cohortId && (
          <Constellation3D
            cohortId={cohortId}
            animals={constellationAnimals}
            focusedId={focusedId}
            onFocus={setFocusedId}
          />
        )}
      </div>

      {/* The chrome, over the sky in two rails (`dashboard.md` §2.1, the
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
              // startedAt is the record's *creation* time and is never
              // restamped, so it only means anything once something is
              // recording — until then, "started 11:49" with a ticking counter
              // describes a run that never began. Gated on a box having
              // actually run rather than on the session status, which per-box
              // Start never advances.
              startedAt={hasRun ? (session?.startedAt ?? null) : null}
              groupName={groupInfo?.name ?? null}
            />

            <SessionJourney step={journeyStep} hint={hint} group={groupInfo} compact />

            {error && (
              <div
                className="flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
                style={{ color: "var(--color-status-error)" }}
              >
                <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
                {error}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              {/* Gone, not greyed, once every box is already running: a disabled
                  primary button is the loudest thing in the rail and it is
                  advertising the one action that has nothing left to do. The
                  per-box Start controls remain for a box that later finishes,
                  and this returns the moment one does. */}
              {!allRunning && (
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
                  title="Ends this group's runs, then returns to box confirmation for the next group"
                  onClick={doSwitchGroup}
                >
                  <Users size={13} strokeWidth={1.75} />
                  Switch Group
                </Button>
              )}
              <Button
                variant="ghost"
                disabled={busy || !connected}
                onClick={() =>
                  void run(async () => {
                    // A session that never recorded anything is discarded, not
                    // "ended": marking it completed would seed Analytics with an
                    // empty session — the same rule as the session dock's
                    // Discard. Keyed on whether a box ever ran, NOT on the
                    // session status: boxes started one at a time leave the
                    // status at `configuring` forever, and discarding on that
                    // basis threw away real runs.
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
                  })
                }
              >
                {hasRun ? "End Session" : "Discard session"}
              </Button>
            </div>
          </div>
        </div>

        {/* The box column: one tile per box, or the focused star's instrument
            panel. They SWAP rather than stack — the panel is that box's tile
            opened up, and two absolutely-positioned columns fighting for one
            edge is what the panel's old self-docking amounted to. Six tiles
            scroll inside this rail; the window itself never scrolls. */}
        <div className="scrollbar-none pointer-events-none absolute inset-y-0 right-0 w-[392px] overflow-y-auto p-4 pr-8">
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
                onStart={() => void run(() => startOne(focusedBox.box))}
                onStop={() => void run(() => stopBox(client, focusedBox.box))}
                onReset={() =>
                  void run(() => client.call(CMD.PORT_RESET, { box: focusedBox.box }))
                }
                onBack={() => setFocusedId(null)}
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
        </div>

        {/* Centre stage, between the rails: the moments that are about the
            whole rig rather than one box, and that the operator has to act on
            before anything else means much. */}
        <div className="pointer-events-none absolute inset-y-0 left-[392px] right-[392px] flex items-center justify-center p-6">
          <AnimatePresence mode="popLayout">
            {groupDone && !lastGroup ? (
              /* §5.5 — the group-swap prompt: every box in this group has
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
                  caption="All boxes finished — return each animal to its home cage, then switch groups."
                  footer={
                    <Button
                      variant="primary"
                      disabled={busy || !connected}
                      onClick={doSwitchGroup}
                    >
                      <Users size={13} strokeWidth={1.75} />
                      Switch Group
                    </Button>
                  }
                />
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
                      disabled={busy || !connected || !cohort}
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
        </div>
      </motion.div>
    </div>
  );
}

/** §5.1 — everything 24-hour, including the clock that keeps ticking. */
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

  // Whole-session elapsed, from the record's startedAt — a different clock
  // than the per-box ones below, which run from each box's own start.
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
 * Mirroring state, mid-run (`data.md` §7).
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
 * there would punch a hole in it (`dashboard.md` §1.4). Clicking the tile
 * flies to that box's star and opens its panel — the rail swaps to it, so the
 * tile and the panel are one object at two sizes rather than two places the
 * same controls live.
 */
function BoxCard({
  box,
  busy,
  durationMinutes,
  onOpen,
  onStart,
  onStop,
  onReset,
}: {
  box: SessionBox;
  busy: boolean;
  durationMinutes: number | null;
  onOpen: () => void;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
}) {
  const port = usePortStatus(box.box);
  const metrics = useBoxTelemetry(box.box);
  const ended = useBoxEnded(box.box);
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

      {/* §5.3 — Stop is a request the firmware honours at a trial boundary, so
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

      {ended ? (
        <p className="mt-3 text-[11px] text-static">
          Finished — <span className="text-starlight">{ended.stopReason}</span>
        </p>
      ) : (
        <MetricStrip box={box.box} metrics={metrics} />
      )}
    </section>
  );
}

/**
 * One box's run clock (§5.4): elapsed since *this box's* start, against the
 * session's optional time limit. Driven by the snapshot's `startedAt` rather
 * than a client-side stopwatch, so a reloaded window resumes mid-count. Once
 * time is up the sidecar has already sent STOP — the line says so instead of
 * counting on, because the run now ends at the board's next trial boundary.
 */
function ElapsedClock({
  startedAt,
  live,
  durationMinutes,
}: {
  startedAt: string | null;
  live: boolean;
  durationMinutes: number | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live || !startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live, startedAt]);

  if (!live || !startedAt) return null;
  const elapsed = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const limit = durationMinutes !== null ? durationMinutes * 60 : null;
  const timeUp = limit !== null && elapsed >= limit;

  return (
    <div
      className="mt-1 font-mono text-[11px] tabular-nums text-static"
      style={timeUp ? { color: "var(--color-status-warning)" } : undefined}
    >
      {clockSpan(elapsed)}
      {limit !== null && ` / ${clockSpan(limit)}`}
      {timeUp && " · time up — stopping at the next trial boundary"}
    </div>
  );
}

/** Seconds as m:ss, growing to h:mm:ss for long sessions. */
function clockSpan(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

function StateChip({ state, reason }: { state: string; reason: string }) {
  const color =
    state === "IN_SESSION"
      ? "var(--color-status-ok)"
      : state === "ERROR"
        ? "var(--color-status-error)"
        : "var(--color-static)";
  return (
    <span
      title={reason}
      className="shrink-0 rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[10px]"
      style={{ color }}
    >
      {state}
    </span>
  );
}
