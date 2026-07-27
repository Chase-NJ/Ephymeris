import { AnimatePresence, motion } from "framer-motion";
import { CircleAlert, Play, RotateCcw, Square, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { useBackupStatus } from "@/lib/backup/useBackupStatus";
import { Constellation3D } from "@/components/sessions/Constellation3D";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { MetricStrip } from "@/components/sessions/MetricStrip";
import { StarPanel } from "@/components/sessions/StarPanel";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { useAllPortStatuses, usePortStatus } from "@/lib/hardware/context";
import { springPanel } from "@/lib/motion";
import {
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
import { populatedGroups, type SessionBox, type SessionSnapshot } from "@/lib/sessions/types";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Mission Control (`starting-a-session.md` §5–§6).
 *
 * The 3D constellation is the centerpiece (§6); the per-box cards stay below it
 * because §6.2 makes an unlit star deliberately inert — Start for a box that
 * isn't running yet has to be reachable somewhere, and §6.4 describes the
 * panel's controls as the same actions "just reachable from here too".
 */
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

  // §6.2 — every animal in the cohort gets a star; only those whose box is
  // actually IN_SESSION are lit and interactive. An animal in a group that
  // isn't running, or with no box at all, is present but inert.
  const portStates = useAllPortStatuses();
  const constellationAnimals = useMemo(() => {
    const boxOf = new Map(boxes.map((b) => [b.animalId, b.box]));
    return (cohort?.animals ?? []).map((animal) => {
      const box = boxOf.get(animal.id);
      return {
        animalId: animal.id,
        name: animal.name,
        lit: box !== undefined && portStates[box]?.state === "IN_SESSION",
      };
    });
  }, [cohort, boxes, portStates]);

  const [focusedId, setFocusedId] = useState<string | null>(null);
  const focusedBox = boxes.find((b) => b.animalId === focusedId) ?? null;

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

  const lastGroup = groupInfo === null || groupInfo.index === groupInfo.count;
  const journeyStep = groupDone && lastGroup ? ("finish" as const) : ("run" as const);
  const hint = !connected
    ? "Waiting for the hardware service…"
    : boxes.length === 0
      ? "No boxes in this group — switch group or end the session."
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

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-5xl px-8 py-8"
    >
      <SessionJourney step={journeyStep} hint={hint} group={groupInfo} />
      <Header
        name={sessionName ?? "—"}
        date={session?.date ?? ""}
        startedAt={session?.startedAt ?? null}
        groupName={groupInfo?.name ?? null}
      />

      {error && (
        <div
          className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
          style={{ color: "var(--color-status-error)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          {error}
        </div>
      )}

      <div className="mt-5 flex items-center gap-2">
        <Button
          variant="primary"
          disabled={busy || !connected || boxes.length === 0 || allRunning}
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
        {multiGroup && (
          <Button
            disabled={busy || !connected}
            title="Ends this group's runs, then returns to box confirmation for the next group"
            onClick={() =>
              void run(async () => {
                const next = await switchGroup(client, sessionId!);
                // No group left to run means the session is over — land on
                // Analytics, same as an explicit End Session.
                if (next === null) {
                  navigate("/analytics", { state: { endedSession: sessionName } });
                  return;
                }
                navigate(
                  `/session/${sessionId}/mapping?cohort=${cohortId}&group=${next}`,
                );
              })
            }
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
              await endSession(client, sessionId!);
              navigate("/analytics", { state: { endedSession: sessionName } });
            })
          }
        >
          End Session
        </Button>
      </div>

      {boxes.length === 0 ? (
        <p className="mt-6 text-[13px] text-static">
          No boxes are configured for this session yet.
        </p>
      ) : (
        <>
          <div className="relative mt-5 h-[440px] overflow-hidden rounded-lg border border-halo">
            {cohort && (
              <Constellation3D
                cohortId={cohort.id}
                animals={constellationAnimals}
                focusedId={focusedId}
                onFocus={setFocusedId}
              />
            )}
            <AnimatePresence>
              {focusedBox && (
                <StarPanel
                  key={focusedBox.box}
                  box={focusedBox}
                  busy={busy || !connected}
                  onStart={() => void run(() => startOne(focusedBox.box))}
                  onStop={() => void run(() => stopBox(client, focusedBox.box))}
                  onReset={() =>
                    void run(() => client.call(CMD.PORT_RESET, { box: focusedBox.box }))
                  }
                  onBack={() => setFocusedId(null)}
                />
              )}
            </AnimatePresence>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
            {boxes.map((box) => (
              <BoxCard
                key={box.box}
                box={box}
                busy={busy || !connected}
                onStart={() => void run(() => startOne(box.box))}
                onStop={() => void run(() => stopBox(client, box.box))}
                onReset={() => void run(() => client.call(CMD.PORT_RESET, { box: box.box }))}
              />
            ))}
          </div>
        </>
      )}
    </motion.section>
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
        <div className="font-mono text-[26px] tabular-nums text-starlight">
          {clock24(now)}
        </div>
      </div>
    </div>
  );
}

/**
 * Mirroring state, mid-run (`data-saving.md` §8).
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

function BoxCard({
  box,
  busy,
  onStart,
  onStop,
  onReset,
}: {
  box: SessionBox;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
}) {
  const port = usePortStatus(box.box);
  const metrics = useBoxTelemetry(box.box);
  const ended = useBoxEnded(box.box);
  const live = port.state === "IN_SESSION";

  return (
    <div className="surface rounded-md p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-starlight">
            Box {box.box} · {box.animalName}
          </div>
          <div className="truncate font-mono text-[11px] text-static">
            {box.sketchName}
          </div>
        </div>
        <StateChip state={port.state} reason={port.reason} />
      </div>

      {/* §5.3 — Stop is a request the firmware honours at a trial boundary, so
          it stays available while the box is live and doesn't force a state. */}
      <div className="mt-3 flex items-center gap-2">
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
    </div>
  );
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
