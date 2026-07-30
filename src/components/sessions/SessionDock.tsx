import { ArrowRight, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import { useAllPortStatuses } from "@/lib/hardware/context";
import { abandonSession, endSession } from "@/lib/sessions/commands";
import {
  useActiveLoaded,
  useActiveSessions,
  useEndedCount,
} from "@/lib/sessions/context";
import { firstGroupToRun, type Session, type SessionSnapshot } from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * The session dock — everything `sessions.active` reports, docked beside the
 * Dashboard's hero CTA (dashboard.md §3). This is the former Launch
 * page's content in panel form: the running session with its way back into
 * Mission Control, set-ups still in `configuring` with Resume/Discard, and
 * crash-orphaned `stale` rows shown read-only. The dock renders whatever the
 * sidecar reports and stays current via `session.lifecycle` — nothing here is
 * predicted client-side, per the sidecar-is-authoritative rule. Per-box
 * liveness comes from `port.state`, not the snapshot's point-in-time flags.
 *
 * Renders nothing when there is nothing to act on — the hero alone is the
 * whole story then — and nothing before `sessions.active` has answered, per
 * the Dashboard's no-spinner rule.
 *
 * Crash-orphaned sessions (`stale`) are shown read-only: their data is on disk
 * via the write-ahead `.tsv`, but resumption after a restart is out of scope
 * by decision — Close Out marks them completed, nothing offers to resume.
 */
export function SessionDock() {
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const active = useActiveSessions();
  const loaded = useActiveLoaded();

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Which confirm dialog is open, if any. */
  const [confirm, setConfirm] = useState<
    | { kind: "end"; session: Session }
    | { kind: "discard"; session: Session }
    | { kind: "closeout"; session: Session }
    | null
  >(null);

  const connected = status === "connected";
  const running = active?.running ?? null;
  const configuring = active?.configuring ?? [];
  const stale = active?.stale ?? [];

  if (!connected || !loaded) return null;
  if (!running && configuring.length === 0 && stale.length === 0 && !error) return null;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  /** Step 2 needs `?group=`; the session record doesn't carry it, so re-derive
   *  the first runnable group the same way Step 1 would have. */
  async function resumeSetup(session: Session) {
    await run(async () => {
      const cohort = await getCohort(client, session.cohortId);
      const group = firstGroupToRun(cohort);
      if (!group) {
        throw new Error(
          "This session's cohort no longer has a box-assigned group — discard the session instead.",
        );
      }
      navigate(`/session/${session.id}/mapping?cohort=${session.cohortId}&group=${group.id}`);
    });
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3">
      {error && (
        <div
          className="flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
          style={{ color: "var(--color-status-error)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          {error}
        </div>
      )}

      {running && (
        <RunningCard
          snapshot={running}
          busy={busy}
          onOpen={() =>
            navigate(`/session/${running.session.id}/control?cohort=${running.session.cohortId}`)
          }
          onEnd={() => setConfirm({ kind: "end", session: running.session })}
        />
      )}

      {configuring.length > 0 && (
        <section>
          <h2 className="text-[12px] font-medium text-starlight">
            Set-up in progress
            <span className="ml-2 font-sans text-[11px] font-normal text-static">
              created but never started
            </span>
          </h2>
          <div className="mt-2 flex flex-col gap-2">
            {configuring.map((session) => (
              <SessionRow key={session.id} session={session}>
                <Button disabled={busy || !connected} onClick={() => void resumeSetup(session)}>
                  Resume setup
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy || !connected}
                  onClick={() => setConfirm({ kind: "discard", session })}
                >
                  Discard
                </Button>
              </SessionRow>
            ))}
          </div>
        </section>
      )}

      {stale.length > 0 && (
        <section>
          <h2
            className="text-[12px] font-medium"
            style={{ color: "var(--color-status-warning)" }}
          >
            Ended unexpectedly
            <span className="ml-2 font-sans text-[11px] font-normal text-static">
              recorded data is safe on disk; a session can&apos;t resume after a restart
            </span>
          </h2>
          <div className="mt-2 flex flex-col gap-2">
            {stale.map((session) => (
              <SessionRow key={session.id} session={session}>
                <Button
                  disabled={busy || !connected}
                  onClick={() =>
                    navigate("/analytics", {
                      state: { cohortId: session.cohortId, sessionId: session.id },
                    })
                  }
                >
                  View in Analytics
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy || !connected}
                  onClick={() => setConfirm({ kind: "closeout", session })}
                >
                  Close out
                </Button>
              </SessionRow>
            ))}
          </div>
        </section>
      )}

      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={
          confirm?.kind === "end"
            ? "End this session?"
            : confirm?.kind === "discard"
              ? "Discard this set-up?"
              : "Close out this session?"
        }
      >
        {confirm && (
          <>
            <p className="text-[13px] text-static">
              {confirm.kind === "end" &&
                "Every running box is stopped gracefully, files are finalized, and the session is marked completed."}
              {confirm.kind === "discard" &&
                "The session record is marked aborted. Nothing was recorded, so nothing on disk is touched."}
              {confirm.kind === "closeout" &&
                "The session is marked completed as-is. Data already written to disk stays exactly where it is."}
            </p>
            <p className="mt-2 font-mono text-[12px] text-starlight">
              {sessionName(confirm.session)} · {confirm.session.date}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirm(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => {
                  const { kind, session } = confirm;
                  void run(async () => {
                    if (kind === "discard") {
                      await abandonSession(client, session.id);
                      return;
                    }
                    await endSession(client, session.id);
                    if (kind === "end") {
                      // Same landing as Mission Control's End Session — Analytics
                      // opens on the run just finished, not an empty picker.
                      navigate("/analytics", {
                        state: {
                          endedSession: sessionName(session),
                          cohortId: session.cohortId,
                          sessionId: session.id,
                        },
                      });
                    }
                  });
                }}
              >
                {confirm.kind === "end"
                  ? "End Session"
                  : confirm.kind === "discard"
                    ? "Discard"
                    : "Close Out"}
              </Button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

function sessionName(session: Session): string {
  return `${session.prefixName}_${session.sessionNumber}`;
}

/** The dock's centerpiece while something is running: status at a glance plus
 *  the way back in. Telemetry charts stay in Mission Control — this is the
 *  door, not a second cockpit. */
function RunningCard({
  snapshot,
  busy,
  onOpen,
  onEnd,
}: {
  snapshot: SessionSnapshot;
  busy: boolean;
  onOpen: () => void;
  onEnd: () => void;
}) {
  const { client, status } = useSidecar();
  const portStates = useAllPortStatuses();
  const endedCount = useEndedCount();
  const [groupName, setGroupName] = useState<string | null>(null);

  const { session, groupId, boxes } = snapshot;

  // The group's display name lives on the cohort; degrade to nothing if the
  // fetch fails — the raw id would only be noise to a lab user.
  useEffect(() => {
    if (status !== "connected" || !groupId) return;
    let alive = true;
    void getCohort(client, session.cohortId)
      .then((cohort) => {
        if (!alive) return;
        setGroupName(cohort.groups.find((g) => g.id === groupId)?.name ?? null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [client, status, session.cohortId, groupId]);

  const runningCount = boxes.filter(
    (b) => portStates[b.box]?.state === "IN_SESSION",
  ).length;

  return (
    <div className="hud rounded-md p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-2">
          <span
            className="inline-block size-[7px] rounded-full"
            style={{ background: "var(--color-status-ok)" }}
          />
          <h2 className="font-mono text-[14px] text-starlight">{sessionName(session)}</h2>
        </div>
        <p className="font-mono text-[11px] text-static">
          {runningCount} of {boxes.length} boxes recording
          {endedCount > 0 && ` · ${endedCount} finished`}
        </p>
      </div>
      <p className="mt-1 font-mono text-[11px] text-static">
        {session.date}
        {` · started ${clock24(new Date(session.startedAt))}`}
        {groupName && ` · ${groupName}`}
      </p>

      {boxes.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-x-5 gap-y-1.5">
          {boxes.map((box) => {
            const state = portStates[box.box]?.state ?? "IDLE";
            const live = state === "IN_SESSION";
            return (
              <div key={box.box} className="flex items-center gap-2 text-[12px]">
                <span
                  className="inline-block size-[5px] shrink-0 rounded-full"
                  style={{
                    background: live
                      ? "var(--color-status-ok)"
                      : state === "ERROR"
                        ? "var(--color-status-error)"
                        : "var(--color-halo)",
                  }}
                />
                <span className="text-static">Box {box.box}</span>
                <span className="truncate text-starlight">{box.animalName}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        <Button variant="primary" disabled={busy} onClick={onOpen}>
          Open Mission Control
          <ArrowRight size={13} strokeWidth={2} />
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onEnd}>
          End Session
        </Button>
      </div>
    </div>
  );
}

function SessionRow({ session, children }: { session: Session; children: React.ReactNode }) {
  return (
    <div className="hud flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2.5">
      <div className="min-w-0">
        <div className="font-mono text-[13px] text-starlight">{sessionName(session)}</div>
        <div className="mt-0.5 font-mono text-[11px] text-static">
          {session.date} · created {clock24(new Date(session.startedAt))}
        </div>
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

function clock24(when: Date): string {
  return when.toLocaleTimeString("en-GB", { hour12: false });
}
