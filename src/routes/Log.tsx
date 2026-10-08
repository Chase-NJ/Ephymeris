import { motion } from "framer-motion";
import { Keyboard, NotebookPen } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router";

import { ChangeCohort } from "@/components/analytics/ChangeCohort";
import { FolderButton } from "@/components/common/FolderButton";
import { CohortManifest } from "@/components/cohorts/CohortManifest";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { DENSE_SKY_OPACITY, SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { CarryForwardPanel } from "@/components/logbook/CarryForwardPanel";
import { LogExport } from "@/components/logbook/LogExport";
import { LogRail } from "@/components/logbook/LogRail";
import { MonthStrip } from "@/components/logbook/MonthStrip";
import { SessionReadout } from "@/components/logbook/SessionReadout";
import { useAnimalNames, useRoster } from "@/components/logbook/useRoster";
import { useAnalyticsStore, useSummary } from "@/lib/analytics/context";
import { useCohorts } from "@/lib/cohorts/context";
import { resolveFlag } from "@/lib/logbook/commands";
import { useLogbook, useLogbookStore, useLogCohort, useLogSession } from "@/lib/logbook/context";
import { newestFirst, stepFrom } from "@/lib/logbook/rail";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/**
 * The lab notebook (`USER-GUIDE.md#keeping-the-log`, `DATA.md#the-session-log`).
 *
 * A cohort's sessions on the flight-recorder rail at the left; the selected
 * one's page on the right. Picking a cohort is the same list Analytics opens
 * on (`CohortManifest`) — one way to choose a cohort across the app.
 *
 * The keyboard is first-class because a notebook is used with hands full:
 * j / k (or the arrows, on the rail) step through sessions from anywhere on
 * the page, and n jumps to the note box.
 */
export function Log() {
  const { client, status } = useSidecar();
  const store = useLogbookStore();
  const analytics = useAnalyticsStore();
  const cohorts = useCohorts();
  const pickable = useMemo(() => cohorts.filter((c) => !c.archived), [cohorts]);
  const location = useLocation();
  const connected = status === "connected";

  const cohortId = useLogCohort();
  const selectedId = useLogSession();
  const entry = useLogbook(cohortId);
  const active = cohorts.find((c) => c.id === cohortId) ?? null;
  // The data folder rides the Analytics summary, as on that page; the session
  // page asks for the summary, so it is here by the time anyone looks.
  const dataFolder = useSummary(cohortId)?.dataFolder ?? null;
  const roster = useRoster(cohortId);
  const names = useAnimalNames(roster);
  const composer = useRef<HTMLTextAreaElement>(null);

  // Arriving with a cohort and session (the wrap-up, a carry-forward link)
  // goes straight there; arriving cold picks up whichever cohort Analytics
  // was last looking at, else the cohort list.
  const landing = location.state as { cohortId?: string; sessionId?: string } | null;
  const handled = useRef<string | null>(null);
  useEffect(() => {
    if (handled.current === location.key) return;
    handled.current = location.key;
    if (landing?.cohortId) {
      store.selectCohort(landing.cohortId);
      if (landing.sessionId) store.selectSession(landing.sessionId);
    } else if (store.getCohortId() === null && analytics.getCohortId() !== null) {
      store.selectCohort(analytics.getCohortId());
    }
  }, [location.key, landing?.cohortId, landing?.sessionId, store, analytics]);

  useEffect(() => {
    if (connected && cohortId) void store.load(cohortId);
  }, [connected, cohortId, store]);

  // Rest on a real session: the running one if there is one, else the newest.
  const sessions = entry.sessions;
  useEffect(() => {
    if (sessions.length === 0) return;
    if (selectedId && sessions.some((s) => s.id === selectedId)) return;
    const live = sessions.find((s) => s.status === "running");
    store.selectSession(live?.id ?? newestFirst(sessions)[0]!.id);
  }, [sessions, selectedId, store]);

  const order = useMemo(() => newestFirst(sessions).map((s) => s.id), [sessions]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;
      // The rail handles its own keys when it has focus.
      if (event.target instanceof HTMLElement && event.target.getAttribute("role") === "listbox") return;
      if (event.key === "j" || event.key === "k") {
        event.preventDefault();
        const next = stepFrom(order, store.getSessionId(), event.key === "j" ? 1 : -1);
        if (next) store.selectSession(next);
      } else if (event.key === "n") {
        event.preventDefault();
        composer.current?.focus();
        composer.current?.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, store]);

  const noteCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const [id, notes] of entry.notesBySession) counts.set(id, notes.length);
    return counts;
  }, [entry.notesBySession]);
  const flagged = useMemo(
    () => new Set(entry.openFlags.map((n) => n.sessionId)),
    [entry.openFlags],
  );
  const selected = sessions.find((s) => s.id === selectedId) ?? null;

  if (!cohortId) {
    return (
      <div className="relative h-full">
        <SkyBackdrop opacity={DENSE_SKY_OPACITY} />
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springPanel}
          className="pointer-events-none absolute inset-0"
        >
          <div className="pointer-events-auto absolute inset-x-8 top-4 bottom-6 flex max-w-[820px] flex-col">
            <h1 className="font-display text-[22px] text-starlight">Log</h1>
            <p className="mt-1 text-[12px] leading-relaxed text-static">
              Pick a cohort to open its lab notebook — every session, its notes, and what
              changed between them.
            </p>
            {!connected && (
              <p className="mt-4 text-[13px] text-static">
                Waiting for the backend — the log is kept by it.
              </p>
            )}
            {connected && pickable.length === 0 && (
              <p className="mt-4 text-[13px] text-static">
                No cohorts yet — the log keeps sessions recorded against one.
              </p>
            )}
            {connected && pickable.length > 0 && (
              <div className="mt-5 flex min-h-0 flex-col">
                <CohortManifest cohorts={pickable} onPick={(id) => store.selectCohort(id)} />
              </div>
            )}
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="relative h-full">
      <SkyBackdrop opacity={DENSE_SKY_OPACITY} />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springPanel}
        className="absolute inset-0 flex flex-col"
      >
        <header className="mx-auto flex w-full max-w-6xl shrink-0 flex-wrap items-start justify-between gap-3 px-8 pt-8">
          <div className="flex items-start gap-3">
            <span className="-mt-1 flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <NotebookPen size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">Log</h1>
              <ChangeCohort
                name={active?.name ?? "Cohort"}
                disc={
                  active ? (
                    <PlanetDisc cohortId={active.id} appearance={active.appearance} size={16} />
                  ) : undefined
                }
                onBack={() => store.selectCohort(null)}
              />
              <p className="mt-1.5 font-mono text-[11px] text-static">
                {sessions.length} session{sessions.length === 1 ? "" : "s"} ·{" "}
                {[...noteCounts.values()].reduce((a, b) => a + b, 0)} notes
                {entry.openFlags.length > 0 && ` · ${entry.openFlags.length} open flag${entry.openFlags.length === 1 ? "" : "s"}`}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-2">
            {/* The cohort's data folder, beside the exports: the other way the
                log leaves the app. The selected session's own folder opens
                from its page header. */}
            {dataFolder && <FolderButton path={dataFolder} label="Cohort folder" />}
            <LogExport
              cohortId={cohortId}
              cohortName={active?.name ?? "Cohort"}
              entry={entry}
              session={selected}
              names={names}
            />
          </div>
        </header>

        <div className="mx-auto mt-5 flex min-h-0 w-full max-w-6xl flex-1 gap-5 px-8 pb-6">
          <aside className="hud flex w-[272px] shrink-0 flex-col overflow-hidden rounded-lg">
            <MonthStrip
              sessions={sessions}
              selectedId={selectedId}
              onSelect={(id) => store.selectSession(id)}
            />
            {entry.state === "loading" && sessions.length === 0 ? (
              <p className="p-4 text-[12px] text-static">Reading the log…</p>
            ) : sessions.length === 0 ? (
              <p className="p-4 text-[12px] leading-relaxed text-static">
                {entry.error ?? "No sessions recorded for this cohort yet."}
              </p>
            ) : (
              <LogRail
                sessions={sessions}
                selectedId={selectedId}
                onSelect={(id) => store.selectSession(id)}
                noteCounts={noteCounts}
                flagged={flagged}
              />
            )}
            <p className="flex items-center gap-2 border-t border-halo px-3 py-2 font-mono text-[10px] text-static/80">
              <Keyboard size={12} strokeWidth={1.75} aria-hidden />
              j / k step · n note · PgUp / PgDn month
            </p>
          </aside>

          <main className="scrollbar-none min-h-0 flex-1 overflow-y-auto pb-8">
            <div className="flex flex-col gap-4">
              <CarryForwardPanel
                flags={entry.openFlags}
                sessions={sessions}
                names={names}
                onOpen={(id) => store.selectSession(id)}
                onResolve={async (note) => {
                  await resolveFlag(client, note.id, true, null);
                }}
              />
              {selected && (
                <SessionReadout
                  cohortId={cohortId}
                  session={selected}
                  entry={entry}
                  roster={roster}
                  names={names}
                  composerRef={composer}
                />
              )}
            </div>
          </main>
        </div>
      </motion.div>
    </div>
  );
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}
