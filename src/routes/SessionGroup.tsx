import { motion } from "framer-motion";
import { ArrowRight, CircleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { GroupPicker } from "@/components/sessions/GroupPicker";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { SettingGroup } from "@/components/settings/SettingRow";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { endSession, resumeSession, sessionStatus } from "@/lib/sessions/commands";
import { useActiveSessions } from "@/lib/sessions/context";
import { clearSetupResume } from "@/lib/sessions/setupResume";
import {
  allGroupsRun,
  groupRunsFor,
  isContinuable,
  localToday,
  populatedGroups,
  type Session,
} from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * The group step (`ARCHITECTURE.md#group-step`) — which group goes on the rig next.
 *
 * Reached from Mission Control after a group ends (`sessions.endGroup`), and
 * from the Dashboard or Step 1 to continue one of today's sessions that the app
 * closed on between groups, or that was ended too early. For the second kind
 * the session is re-held (`sessions.resume`) only when the operator commits to
 * a group — backing out of this page changes nothing.
 *
 * There is no run order to follow: every populated group is offered, a group
 * that already ran says when, and running it again is allowed.
 */
export function SessionGroup() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const active = useActiveSessions();
  const connected = status === "connected";

  const [session, setSession] = useState<Session | null>(null);
  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const running = active?.running ?? null;
  const held = running?.session.id === sessionId ? running : null;
  // Re-read on every lifecycle change: `groupRuns` is what the badges show.
  const lifecycleKey = held ? `${held.session.status}:${held.session.groupRuns.length}` : "";

  useEffect(() => {
    if (!connected || !sessionId) return;
    let alive = true;
    void sessionStatus(client, sessionId)
      .then(async (snapshot) => {
        if (!alive) return;
        setSession(snapshot.session);
        const loaded = await getCohort(
          client,
          params.get("cohort") || snapshot.session.cohortId,
        );
        if (alive) setCohort(loaded);
      })
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [client, connected, sessionId, params, lifecycleKey]);

  // A group is already mapped on the rig: this page is not the next step.
  useEffect(() => {
    if (held && held.groupId) {
      navigate(`/session/${sessionId}/control?cohort=${held.session.cohortId}`, {
        replace: true,
      });
    }
  }, [held, navigate, sessionId]);

  // Pre-select the first group that hasn't run, so the common case is one press.
  useEffect(() => {
    if (!cohort || groupId !== null) return;
    const groups = populatedGroups(cohort);
    const fresh = groups.find((g) => groupRunsFor(session, g.id).length === 0);
    if (fresh) setGroupId(fresh.id);
    else if (groups.length === 1) setGroupId(groups[0]!.id);
  }, [cohort, session, groupId]);

  const name = session ? `${session.prefixName}_${session.sessionNumber}` : "";
  const today = localToday();
  const needsResume = session !== null && held === null;
  const resumable = session !== null && isContinuable(session, today);
  const blocked = needsResume && !resumable;
  const otherHeld =
    needsResume && active?.running != null && active.running.session.id !== sessionId;
  const everyGroupRan = cohort && session ? allGroupsRun(cohort, session) : false;

  const ranNames = useMemo(() => {
    if (!cohort || !session) return [];
    const names = new Map(cohort.groups.map((g) => [g.id, g.name]));
    return session.groupRuns.map((run) => names.get(run.groupId) ?? "a removed group");
  }, [cohort, session]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function runGroup() {
    if (!session || !groupId) return;
    void run(async () => {
      if (needsResume) await resumeSession(client, session.id);
      navigate(
        `/session/${session.id}/mapping?cohort=${session.cohortId}&group=${groupId}` +
          (session.recording != null ? "&recording=1" : ""),
      );
    });
  }

  function finish() {
    if (!session) return;
    void run(async () => {
      await endSession(client, session.id);
      clearSetupResume();
      navigate("/analytics", {
        state: { endedSession: name, cohortId: session.cohortId, sessionId: session.id },
      });
    });
  }

  const hint = !connected
    ? "Waiting for the hardware service…"
    : !session || !cohort
      ? "Loading the session…"
      : blocked
        ? "Only today's sessions can be continued."
        : otherHeld
          ? "Another session is open — end it first."
          : groupId === null
            ? "Pick the group going on the rig next."
            : everyGroupRan
              ? "Every group has run — run one again, or end the session."
              : "Ready — continue to box mapping.";

  return (
    <div className="relative h-full">
      <SkyBackdrop />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-4xl px-8 py-8">
          <SessionJourney
            step="configure"
            hint={hint}
            recording={session?.recording != null}
          />
          <h1 className="font-display text-[22px] text-starlight">
            {needsResume ? "Continue a Session" : "Next Group"}
          </h1>
          {session && (
            <p className="mt-1 font-mono text-[12px] text-static">
              {name} · {session.date}
              {ranNames.length > 0 && ` · ran ${ranNames.join(", ")}`}
            </p>
          )}

          {error && (
            <div
              className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
              {error}
            </div>
          )}

          <motion.div variants={CASCADE} initial="hidden" animate="shown">
            <motion.div variants={RISE}>
              <SettingGroup title="Group" variant="hud">
                <div className="p-4">
                  {cohort ? (
                    <GroupPicker
                      cohort={cohort}
                      session={session}
                      value={groupId}
                      onChange={setGroupId}
                    />
                  ) : (
                    <p className="text-[12px] text-static">Loading…</p>
                  )}
                  {blocked && (
                    <p
                      className="mt-3 text-[12px] leading-relaxed"
                      style={{ color: "var(--color-status-warning)" }}
                    >
                      This session is from {session?.date}. Its folder is named for that
                      day, so today&apos;s runs belong in a new session.
                    </p>
                  )}
                  {groupId !== null && groupRunsFor(session, groupId).length > 0 && (
                    <p className="mt-3 text-[12px] leading-relaxed text-static">
                      This group already ran in this session. Running it again adds new
                      timestamped files beside the earlier ones — nothing is overwritten.
                    </p>
                  )}
                </div>
              </SettingGroup>
            </motion.div>

            <motion.div variants={RISE} className="mt-6 flex items-center gap-2">
              <Button
                variant="primary"
                onClick={runGroup}
                disabled={!connected || busy || !groupId || blocked || otherHeld}
              >
                Run this group
                <ArrowRight size={13} strokeWidth={2} />
              </Button>
              {needsResume ? (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    clearSetupResume();
                    navigate("/");
                  }}
                >
                  Cancel
                </Button>
              ) : (
                <Button variant="ghost" disabled={busy || !session} onClick={finish}>
                  End session
                </Button>
              )}
            </motion.div>
          </motion.div>
        </section>
      </motion.div>
    </div>
  );
}
