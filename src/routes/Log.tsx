import { motion } from "framer-motion";
import { BookOpenText, Bookmark, Keyboard, NotebookPen } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";

import { ChangeCohort } from "@/components/analytics/ChangeCohort";
import { CohortManifest } from "@/components/cohorts/CohortManifest";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { Button } from "@/components/common/controls";
import { FolderButton } from "@/components/common/FolderButton";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { LogExport } from "@/components/logbook/LogExport";
import { ContentsPage, TitlePage } from "@/components/logbook/paper/FrontPages";
import { Notebook, type EdgeTab, type Side } from "@/components/logbook/paper/Notebook";
import type { ComposeRequest } from "@/components/logbook/paper/Notes";
import { paperAnimalColors } from "@/components/logbook/paper/parts";
import { SessionRecto, SessionVerso } from "@/components/logbook/paper/SessionPages";
import { useAnimalNames, useRoster } from "@/components/logbook/useRoster";
import { useAnalyticsStore, useDataVersion, useSummary } from "@/lib/analytics/context";
import { useCohorts } from "@/lib/cohorts/context";
import { longDate } from "@/lib/logbook/clock";
import { useLogbook, useLogbookStore, useLogCohort, useLogSession } from "@/lib/logbook/context";
import {
  FRONT,
  contents,
  folios,
  monthOf,
  monthTurn,
  oldestFirst,
  spreadOrder,
  turn,
} from "@/lib/logbook/pages";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/**
 * The Log (`USER-GUIDE.md#keeping-the-log`, `DATA.md#the-session-log`): a
 * cohort's lab notebook, open on the desk.
 *
 * The one screen that steps out of the instrument
 * (`ARCHITECTURE.md#the-paper-exception`). The desk keeps the app's colours
 * and its controls; the notebook on it is paper, typeset, and read by turning
 * pages: one spread per session, oldest first, behind a title page and a
 * table of contents. What a person wrote is on the left page, what was
 * measured on the right.
 *
 * The keyboard is first-class because a notebook is used with hands full:
 * ← and → turn the page from anywhere, PgUp / PgDn jump a month, Home opens
 * the contents and End the latest day, `n` puts the pen on the next note and
 * `w` on the first weight.
 *
 * Picking a cohort is the same list Analytics opens on (`CohortManifest`):
 * one way to choose a cohort across the app.
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
  const summary = useSummary(cohortId);
  const version = useDataVersion();
  // The data folder rides the Analytics summary, as on that page.
  const dataFolder = summary?.dataFolder ?? null;
  const members = useRoster(cohortId);
  const roster = members.animals;
  const names = useAnimalNames(roster, members.former);

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

  // The performance table reads the Analytics summary: the same numbers, the
  // same cache. A cold one can index the whole archive, so it is asked for
  // only once a notebook is actually open.
  useEffect(() => {
    if (!connected || !cohortId) return;
    void analytics.load(client, cohortId);
  }, [analytics, client, cohortId, connected, version]);

  // A fresh summary means the index has just read files, recovered runs'
  // among them, whose parameters the log's what-changed is computed from
  // (`DATA.md#what-changed`). The log is database-only and cheap; ask again.
  useEffect(() => {
    if (summary && cohortId) void store.load(cohortId, true);
  }, [summary, cohortId, store]);

  const sessions = entry.sessions;
  const order = useMemo(() => spreadOrder(sessions), [sessions]);
  const months = useMemo(() => contents(sessions), [sessions]);
  const byId = useMemo(() => new Map(sessions.map((s) => [s.id, s])), [sessions]);
  const latestId = useMemo(() => {
    const ordered = oldestFirst(sessions);
    return ordered[ordered.length - 1]?.id ?? null;
  }, [sessions]);

  // Open at the bookmark: the running session if there is one, else the last
  // written page. The front matter is a place of its own and is left alone.
  useEffect(() => {
    if (sessions.length === 0) return;
    if (selectedId === FRONT || (selectedId && byId.has(selectedId))) return;
    const live = sessions.find((s) => s.status === "running");
    store.selectSession(live?.id ?? latestId);
  }, [sessions, selectedId, byId, latestId, store]);

  const currentId = selectedId !== null && order.includes(selectedId) ? selectedId : FRONT;
  const open = useCallback((id: string) => store.selectSession(id), [store]);
  const step = useCallback(
    (delta: -1 | 1) => {
      const next = turn(order, store.getSessionId() ?? FRONT, delta);
      if (next) store.selectSession(next);
    },
    [order, store],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;
      const here = store.getSessionId() ?? FRONT;
      const go = (id: string | null) => {
        event.preventDefault();
        if (id) store.selectSession(id);
      };
      switch (event.key) {
        case "ArrowLeft":
        case "k":
          return go(turn(order, here, -1));
        case "ArrowRight":
        case "j":
          return go(turn(order, here, 1));
        case "PageUp":
          return go(monthTurn(months, here, -1));
        case "PageDown":
          return go(monthTurn(months, here, 1));
        case "Home":
          return go(FRONT);
        case "End":
          return go(latestId);
        case "n":
          event.preventDefault();
          return putPenOn("textarea[data-note-composer]");
        case "w":
          event.preventDefault();
          return putPenOn("input[data-weigh-in]");
        default:
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, months, latestId, store]);

  // The weights table asks the facing page to start a health note.
  const [request, setRequest] = useState<(ComposeRequest & { sessionId: string }) | null>(null);
  const nonce = useRef(0);
  const healthNote = useCallback((sessionId: string, animalId: string) => {
    nonce.current += 1;
    setRequest({
      sessionId,
      tag: "animal-health",
      scope: { kind: "animal", animalId, box: null },
      nonce: nonce.current,
    });
  }, []);

  const colors = useMemo(() => {
    const known = (summary?.animals ?? []).map((a) => ({ id: a.id }));
    const seen = new Set(known.map((a) => a.id));
    return paperAnimalColors([...known, ...roster.filter((a) => !seen.has(a.id))]);
  }, [summary, roster]);

  const cohortName = active?.name ?? "Cohort";
  const renderSide = useCallback(
    (id: string, side: Side) => {
      if (!cohortId) return null;
      const session = byId.get(id);
      if (!session) {
        return side === "verso" ? (
          <TitlePage
            cohortName={cohortName}
            entry={entry}
            roster={roster}
            names={names}
            colors={colors}
            onOpen={open}
          />
        ) : (
          <ContentsPage months={months} entry={entry} latestId={latestId} onOpen={open} />
        );
      }
      return side === "verso" ? (
        <SessionVerso
          cohortId={cohortId}
          session={session}
          entry={entry}
          roster={roster}
          names={names}
          request={request?.sessionId === id ? request : null}
          onOpen={open}
        />
      ) : (
        <SessionRecto
          cohortId={cohortId}
          session={session}
          entry={entry}
          roster={roster}
          names={names}
          onHealthNote={(animalId) => healthNote(id, animalId)}
        />
      );
    },
    [cohortId, byId, cohortName, entry, roster, names, colors, months, latestId, request, open, healthNote],
  );

  const runningHead = useCallback(
    (id: string, side: Side) => {
      const session = byId.get(id);
      if (side === "verso") {
        return (
          <>
            <span className="truncate">{cohortName}</span>
            <span>{session ? `${session.prefixName}_${session.sessionNumber}` : ""}</span>
          </>
        );
      }
      return (
        <>
          <span className="truncate">{session ? longDate(session.date) : "Contents"}</span>
          <span>Logbook</span>
        </>
      );
    },
    [byId, cohortName],
  );
  const folio = useCallback((id: string, side: Side) => folios(order, id)[side], [order]);

  const tabs = useMemo<EdgeTab[]>(() => {
    const here = monthOf(months, currentId);
    return months.map((month, index) => ({
      key: month.key,
      // The year is said where it changes, and on the first tab.
      label:
        index === 0 || months[index - 1]!.year !== month.year
          ? `${month.short} ’${String(month.year).slice(2)}`
          : month.short,
      target: month.rows[0]!.id,
      current: month.key === here,
      month: Number(month.key.slice(5, 7)) - 1 || 0,
      title: `${month.label}: ${month.rows.length} session${month.rows.length === 1 ? "" : "s"}`,
    }));
  }, [months, currentId]);

  const noteCount = useMemo(
    () => [...entry.notesBySession.values()].reduce((n, list) => n + list.length, 0),
    [entry.notesBySession],
  );
  const selected = byId.get(currentId) ?? null;

  if (!cohortId) {
    return (
      <div className="relative h-full">
        {/* Every route mounts a constellation (`ARCHITECTURE.md#one-sky`). */}
        <SkyBackdrop opacity={0} />
        <div aria-hidden className="desk absolute inset-y-0 right-0 -left-sidebar" />
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          // Owns its own exit, as every route must (`AppShell`).
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="pointer-events-none absolute inset-0"
        >
          <div className="pointer-events-auto absolute inset-x-8 top-4 bottom-6 flex max-w-[820px] flex-col">
            <h1 className="font-display text-[22px] text-starlight">Log</h1>
            <p className="mt-1 text-[12px] leading-relaxed text-static">
              Pick a cohort to open its lab notebook: every session, its notes, its weigh-ins,
              and what changed between them.
            </p>
            {!connected && (
              <p className="mt-4 text-[13px] text-static">
                Waiting for the backend. The notebook is kept by it.
              </p>
            )}
            {connected && pickable.length === 0 && (
              <p className="mt-4 text-[13px] text-static">
                No cohorts yet. A notebook is kept for each one.
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
      <SkyBackdrop opacity={0} />
      <div aria-hidden className="desk absolute inset-y-0 right-0 -left-sidebar" />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="absolute inset-0 flex flex-col"
      >
        <header className="flex shrink-0 flex-wrap items-start justify-between gap-3 px-6 pt-5">
          <div className="flex items-start gap-3">
            <span className="-mt-1 flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <NotebookPen size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">Log</h1>
              <ChangeCohort
                name={cohortName}
                disc={
                  active ? (
                    <PlanetDisc cohortId={active.id} appearance={active.appearance} size={16} />
                  ) : undefined
                }
                onBack={() => store.selectCohort(null)}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              variant="ghost"
              disabled={currentId === FRONT}
              onClick={() => open(FRONT)}
              title="Open the contents  (Home)"
            >
              <BookOpenText size={13} strokeWidth={1.75} />
              Contents
            </Button>
            <Button
              variant="ghost"
              disabled={latestId === null || currentId === latestId}
              onClick={() => latestId && open(latestId)}
              title="Open the latest session  (End)"
            >
              <Bookmark size={13} strokeWidth={1.75} />
              Latest
            </Button>
            <span aria-hidden className="mx-1 h-5 w-px bg-halo" />
            {/* The cohort's data folder, beside the exports: the other way the
                log leaves the app. The open session's own folder is linked
                from its page. */}
            {dataFolder && <FolderButton path={dataFolder} label="Cohort folder" />}
            <LogExport
              cohortId={cohortId}
              cohortName={cohortName}
              entry={entry}
              session={selected}
              names={names}
            />
          </div>
        </header>

        <div className="mx-auto mt-4 min-h-0 w-full max-w-[1480px] flex-1 px-3">
          <Notebook
            order={order}
            currentId={currentId}
            renderSide={renderSide}
            runningHead={runningHead}
            folio={folio}
            tabs={tabs}
            onTurn={step}
            onOpen={open}
            label={`${cohortName} logbook`}
          />
        </div>

        <p className="flex shrink-0 items-center justify-center gap-2 px-6 pt-2 pb-3 font-mono text-[10px] text-static/80">
          <Keyboard size={12} strokeWidth={1.75} aria-hidden />
          ← → turn · PgUp / PgDn month · Home contents · End latest · n note · w weigh
          <span aria-hidden>·</span>
          <span>
            {sessions.length} session{sessions.length === 1 ? "" : "s"}, {noteCount} note
            {noteCount === 1 ? "" : "s"}
            {entry.openFlags.length > 0 &&
              `, ${entry.openFlags.length} open flag${entry.openFlags.length === 1 ? "" : "s"}`}
          </span>
        </p>
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

/** Focus the first such field on the open spread, never one on a leaf in the air. */
function putPenOn(selector: string): void {
  const field = [...document.querySelectorAll<HTMLElement>(selector)].find(
    (element) => !element.closest("[inert]"),
  );
  if (!field) return;
  field.focus();
  field.scrollIntoView({ block: "center", behavior: "smooth" });
}
