import { AnimatePresence, motion } from "framer-motion";
import { BookOpenText, Bookmark, Info, Keyboard, NotebookPen, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";

import { ChangeCohort } from "@/features/analytics/ChangeCohort";
import { CohortManifest } from "@/features/cohorts/CohortManifest";
import { PlanetDisc } from "@/features/cohorts/PlanetDisc";
import { Button } from "@/components/common/controls";
import { FolderButton } from "@/components/common/FolderButton";
import { DENSE_SKY_OPACITY, SkyBackdrop } from "@/features/sky/SkyBackdrop";
import { LogExport } from "./LogExport";
import { ContentsPage, TitlePage } from "./paper/FrontPages";
import { Notebook, type EdgeTab, type Side } from "./paper/Notebook";
import type { ComposeRequest } from "./paper/Notes";
import { paperAnimalColors } from "./paper/parts";
import { SessionRecto, SessionVerso } from "./paper/SessionPages";
import { useAnimalNames, useRoster } from "./useRoster";
import { errorMessage, rescan } from "@/features/analytics/commands";
import { useAnalyticsStore, useDataVersion, useSummary } from "@/features/analytics/context";
import { describeRescan } from "@/features/analytics/rescan";
import { useCohorts } from "@/features/cohorts/context";
import { longDate } from "./clock";
import { useLogbook, useLogbookStore, useLogCohort, useLogSession } from "./context";
import {
  FRONT,
  contents,
  folios,
  monthOf,
  monthTurn,
  oldestFirst,
  spreadOrder,
  turn,
} from "./pages";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/** A held key turns at most one page in this long: a riffle, never a blur. */
const RIFFLE_MS = 130;

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
 *
 * **Three layers, each with its own way in and out.** The sky holds still and
 * is only ever covered, then paused. The desk is an opaque layer over it, so it fades: an
 * opaque layer with no exit sits over the next screen for the whole of the
 * transition and then vanishes (`AppShell`'s rule that every route owns its
 * exit). What lies on the desk, the cohort list or a notebook, crossfades
 * with the other. And a notebook is laid down already open at its page: it is
 * not mounted until its sessions are known, so it never arrives at the title
 * page and turns to the latest session while it is still fading in.
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

  // Where the notebook lies open, decided in the render that first has its
  // sessions: the page asked for, else the bookmark (the running session, or
  // the last written page). An effect would be a render late, and the book
  // would be seen at its title page first.
  const currentId = useMemo(() => {
    if (selectedId === FRONT) return FRONT;
    if (selectedId !== null && byId.has(selectedId)) return selectedId;
    return sessions.find((s) => s.status === "running")?.id ?? latestId ?? FRONT;
  }, [selectedId, byId, sessions, latestId]);
  // The store follows, so a key or a link starts from the page on screen.
  useEffect(() => {
    if (sessions.length > 0 && currentId !== selectedId) store.selectSession(currentId);
  }, [sessions.length, currentId, selectedId, store]);

  // Nothing is known of a notebook until its first read answers; one that
  // answered with an error still opens, on what it has.
  const opened = entry.state === "ready" || entry.state === "error" || sessions.length > 0;

  const open = useCallback((id: string) => store.selectSession(id), [store]);
  const step = useCallback(
    (delta: -1 | 1) => {
      const next = turn(order, store.getSessionId() ?? FRONT, delta);
      if (next) store.selectSession(next);
    },
    [order, store],
  );

  const lastTurn = useRef(0);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;
      const here = store.getSessionId() ?? FRONT;
      const go = (id: string | null) => {
        event.preventDefault();
        // Every turn mounts two pages; a held key asks for thirty a second.
        const now = performance.now();
        if (event.repeat && now - lastTurn.current < RIFFLE_MS) return;
        lastTurn.current = now;
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

  // The archive walk, as Analytics offers it (`DATA.md#reading-the-archive`):
  // session files copied in from another machine have no record here until a
  // rescan finds them, and the notebook is where their absence is noticed.
  const [rescanning, setRescanning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => setNotice(null), [cohortId]);
  async function runRescan() {
    if (!cohortId) return;
    setRescanning(true);
    setNotice(null);
    try {
      const result = await rescan(client, cohortId);
      setNotice(describeRescan(result));
      // The summary is the performance tables'; the log is everything else.
      await Promise.all([analytics.refresh(client, cohortId), store.load(cohortId, true)]);
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setRescanning(false);
    }
  }

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

  // The sky draws while the desk comes up over it, then stops: under an
  // opaque desk it is only work. Paused, never turned to zero opacity: the
  // next route would pay to show it again (`SkyBackdrop`).
  const [covered, setCovered] = useState(false);

  return (
    <div className="relative h-full">
      {/* Every route mounts a constellation (`ARCHITECTURE.md#one-sky`), and
          never inside anything that fades. */}
      <SkyBackdrop opacity={DENSE_SKY_OPACITY} paused={covered} />
      <motion.div
        aria-hidden
        className="desk absolute inset-y-0 right-0 -left-sidebar"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        onAnimationStart={() => setCovered(false)}
        onAnimationComplete={(target) => {
          if (typeof target === "object" && "opacity" in target && target.opacity === 1) {
            setCovered(true);
          }
        }}
      />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit, as every route must (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="absolute inset-0"
      >
        {/* `popLayout` marks the one leaving, which is what stops it taking
            clicks meant for the one arriving under it (`index.css`). */}
        <AnimatePresence mode="popLayout" initial={false}>
          {cohortId ? (
            <motion.div
              key={`notebook:${cohortId}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
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
                          <PlanetDisc
                            cohortId={active.id}
                            appearance={active.appearance}
                            size={16}
                          />
                        ) : undefined
                      }
                      onBack={() => store.selectCohort(null)}
                    />
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Button
                    variant="ghost"
                    disabled={!opened || currentId === FRONT}
                    onClick={() => open(FRONT)}
                    title="Open the contents  (Home)"
                  >
                    <BookOpenText size={13} strokeWidth={1.75} />
                    Contents
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={!opened || latestId === null || currentId === latestId}
                    onClick={() => latestId && open(latestId)}
                    title="Open the latest session  (End)"
                  >
                    <Bookmark size={13} strokeWidth={1.75} />
                    Latest
                  </Button>
                  <span aria-hidden className="mx-1 h-5 w-px bg-halo" />
                  {/* The cohort's data folder, beside the exports: the other
                      way the log leaves the app. The open session's own
                      folder is linked from its page. */}
                  {dataFolder && <FolderButton path={dataFolder} label="Cohort folder" />}
                  <Button
                    variant="outline"
                    onClick={() => void runRescan()}
                    disabled={!connected || rescanning}
                    title="Look for session files no run record points at"
                  >
                    <RefreshCw
                      size={13}
                      strokeWidth={1.75}
                      className={rescanning ? "animate-spin" : ""}
                    />
                    {rescanning ? "Scanning…" : "Rescan"}
                  </Button>
                  <LogExport
                    cohortId={cohortId}
                    cohortName={cohortName}
                    entry={entry}
                    session={selected}
                    names={names}
                  />
                </div>
              </header>

              {notice && (
                <button
                  type="button"
                  onClick={() => setNotice(null)}
                  className="mx-6 mt-3 flex shrink-0 items-center gap-2 rounded-sm border border-halo bg-nebula/60 px-3 py-2 text-left font-mono text-[11px] leading-relaxed text-static"
                >
                  <Info size={14} strokeWidth={1.75} className="shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">{notice}</span>
                  <span className="ml-auto shrink-0 text-static/70">dismiss</span>
                </button>
              )}

              <div className="mx-auto mt-4 min-h-0 w-full max-w-[1480px] flex-1 px-3">
                {opened ? (
                  // Laid down open at its page, in one piece: nothing inside
                  // a notebook animates on mount (`Notebook`).
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={springPanel}
                    className="h-full"
                  >
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
                  </motion.div>
                ) : (
                  // Said only once the wait is worth mentioning: a read takes
                  // a tenth of a second, and words that flash by are a flicker.
                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.6, duration: 0.2 }}
                    className="pt-16 text-center font-mono text-[11px] text-static"
                  >
                    {connected ? "Opening the notebook…" : "Waiting for the backend."}
                  </motion.p>
                )}
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
          ) : (
            <motion.div
              key="cohorts"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
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
          )}
        </AnimatePresence>
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
