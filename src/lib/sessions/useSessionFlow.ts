import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { useAllPortStatuses } from "@/lib/hardware/context";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

import { sessionStatus } from "./commands";
import { useActiveSessions } from "./context";
import { sessionFlow, type SessionFlow } from "./flow";
import type { Session, SessionBox, SessionSnapshot } from "./types";

const NO_BOXES: SessionBox[] = [];

export interface SessionFlowView {
  /** The record, from `sessions.status`; null until it arrives. */
  session: Session | null;
  /**
   * The session's cohort id, known without a round trip whenever the session
   * is in the `sessions.active` answer already held — which is every in-app
   * arrival at a step. Null only until that answer or the record arrives.
   */
  cohortId: string | null;
  cohort: Cohort | null;
  /** This session holds the rig. */
  held: boolean;
  /** The group on the rig; null unless held with a group mapped. */
  rigGroupId: string | null;
  /** The rig's boxes; empty unless held. */
  boxes: SessionBox[];
  flow: SessionFlow;
  /** The latest failure to load the session or its cohort. */
  error: string | null;
  /** Ask again now — after a command whose effect the next render needs. */
  refresh: () => Promise<void>;
}

/**
 * One session as the guided flow sees it (`ARCHITECTURE.md#the-flow`): its
 * record, its cohort, the rig if it holds it, and `sessionFlow`'s answers.
 *
 * Asked of the sidecar, never carried in router state or tallied from events
 * (`ARCHITECTURE.md#replay-on-connect`): `sessions.status` on connect, on every
 * `session.lifecycle`, and on every `session.animalEnded` — the one per-box
 * fact (`SessionBox.ended`) that lifecycle broadcasts leave out. The cohort is
 * fetched once per session.
 *
 * `groupId` names the group a step is about when it is not the rig's: Boxes
 * and Record carry theirs in the URL.
 */
export function useSessionFlow(
  sessionId: string | undefined,
  groupId?: string | null,
): SessionFlowView {
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const active = useActiveSessions();
  const portStates = useAllPortStatuses();

  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Only the newest answer lands: a lifecycle burst can put several asks in
  // flight, and an older reply arriving last would roll the screen back.
  const asked = useRef(0);

  useEffect(() => {
    setSnapshot(null);
    setCohort(null);
    setError(null);
    return () => {
      asked.current += 1;
    };
  }, [sessionId]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    const ask = ++asked.current;
    try {
      const next = await sessionStatus(client, sessionId);
      if (ask !== asked.current) return;
      setSnapshot(next);
      setError(null);
    } catch (err) {
      if (ask === asked.current) setError(errorMessage(err));
    }
  }, [client, sessionId]);

  // `active` is replaced by each `session.lifecycle` and by the answer to
  // `sessions.active` on connect, so this re-asks on both.
  useEffect(() => {
    if (connected) void refresh();
  }, [connected, refresh, active]);

  useEffect(() => client.on(EVT.SESSION_ANIMAL_ENDED, () => void refresh()), [client, refresh]);

  const running = active?.running ?? null;
  const held = sessionId !== undefined && running?.session.id === sessionId;
  const known =
    (held ? running?.session : null) ??
    active?.configuring.find((s) => s.id === sessionId) ??
    active?.stale.find((s) => s.id === sessionId) ??
    null;
  const session = snapshot !== null && snapshot.session.id === sessionId ? snapshot.session : null;
  const cohortId = session?.cohortId ?? known?.cohortId ?? null;

  useEffect(() => {
    if (!connected || !cohortId) return;
    let alive = true;
    void getCohort(client, cohortId)
      .then((loaded) => alive && setCohort(loaded))
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [client, connected, cohortId]);

  // The rig is the held session's alone; the sidecar reports none for any
  // other, and an answer from before a lifecycle change is not trusted to.
  const rigGroupId = held && session ? (snapshot?.groupId ?? null) : null;
  const boxes = held && session ? (snapshot?.boxes ?? NO_BOXES) : NO_BOXES;

  const flow = useMemo(
    () =>
      sessionFlow({
        session,
        cohort: cohort?.id === cohortId ? cohort : null,
        held,
        rigGroupId,
        boxes,
        groupId: groupId ?? null,
        isLive: (box) => portStates[box]?.state === "IN_SESSION",
      }),
    [session, cohort, cohortId, held, rigGroupId, boxes, groupId, portStates],
  );

  return {
    session,
    cohortId,
    cohort: cohort?.id === cohortId ? cohort : null,
    held,
    rigGroupId,
    boxes,
    flow,
    error,
    refresh,
  };
}
