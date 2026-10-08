import { AnimatePresence, motion } from "framer-motion";
import {
  DENSE_SKY_OPACITY,
  SkyBackdrop,
} from "@/components/constellation3d/SkyBackdrop";
import {
  ArchiveRestore,
  Combine,
  ChartLine,
  CircleAlert,
  CircleCheck,
  Download,
  Info,
  Loader2,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";

import { AnimalRail } from "@/components/analytics/AnimalRail";
import { ChangeCohort } from "@/components/analytics/ChangeCohort";
import { CohortManifest } from "@/components/cohorts/CohortManifest";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import type { ReportInput } from "@/components/analytics/report/ReportSheet";
import {
  reportFilename,
  useExportReport,
} from "@/components/analytics/report/useExportReport";
import { CohortTrends } from "@/components/analytics/CohortTrends";
import { Footnote } from "@/components/analytics/Footnote";
import { LearningCurves } from "@/components/analytics/LearningCurves";
import { SessionRail } from "@/components/analytics/SessionRail";
import { SessionStrategy } from "@/components/analytics/SessionStrategy";
import { SessionSummary } from "@/components/analytics/SessionSummary";
import { TidyRecords, describeTidy } from "@/components/analytics/TidyRecords";
import { Button } from "@/components/common/controls";
import { FolderButton } from "@/components/common/FolderButton";
import { errorMessage, recover, rescan } from "@/lib/analytics/commands";
import {
  useAnalyticsStore,
  useDataVersion,
  useIndexProgress,
  useLoadError,
  useLoadState,
  useSelectedCohort,
  useSelectedSession,
  useSessionList,
  useSummary,
} from "@/lib/analytics/context";
import { useRunSeries } from "@/lib/analytics/series";
import { ALL_SESSIONS } from "@/lib/analytics/store";
import type {
  AnalyticsSummary,
  DiskSession,
  RecoverResult,
  TidyPlan,
  RescanPruned,
  RescanResult,
  RunSummary,
  SessionListItem,
} from "@/lib/analytics/types";
import { sessionRunsOf } from "@/lib/analytics/session";
import {
  buildAnimalColors,
  findSessionByFolder,
} from "@/lib/analytics/view";
import { useCohorts } from "@/lib/cohorts/context";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

const NO_RUNS: RunSummary[] = [];

/**
 * The Analytics dashboard — the "Observatory" (`DATA.md#analytics-views`).
 *
 * One route, no tabs. Cohort, session and animal are persistent selectors, and
 * **selection is a filter, not navigation**: picking a session narrows every
 * panel rather than swapping the view, and hovering an animal highlights its
 * curve, its table row and its strategy trail at once.
 */
export function Analytics() {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();
  const cohorts = useCohorts();
  /** What the landing can offer: an archived cohort is not a study you pick up
   *  again. */
  const pickable = useMemo(() => cohorts.filter((c) => !c.archived), [cohorts]);
  const location = useLocation();

  const cohortId = useSelectedCohort();
  const sessions = useSessionList(cohortId);
  const summary = useSummary(cohortId);
  const state = useLoadState(cohortId);
  const loadError = useLoadError(cohortId);
  const progress = useIndexProgress();
  const sessionScope = useSelectedSession();
  const version = useDataVersion();

  const [rescanning, setRescanning] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [tidyOpen, setTidyOpen] = useState(false);
  const [rescanNote, setRescanNote] = useState<string | null>(null);
  // Bumped whenever the data underneath changes identity — a cohort swap or a
  // rescan. Panels key their draw-on animations off it, so a reveal replays
  // for genuinely new data and not for a hover.
  const [reveal, setReveal] = useState(0);

  // Ending a session lands here with that cohort and session already
  // selected, so the guided flow's last step is a payoff rather than an
  // acknowledgement. A Dashboard row arrives the same way, naming a session by
  // its folder rather than its id (`sessionFolder`) because the rows it comes
  // from are a walk of directory names.
  const landing = location.state as {
    endedSession?: string | null;
    cohortId?: string;
    sessionId?: string;
    sessionFolder?: DiskSession;
  } | null;
  const [banner, setBanner] = useState<string | null>(
    landing?.endedSession ?? null,
  );

  const active = cohorts.find((cohort) => cohort.id === cohortId) ?? null;
  const connected = status === "connected";

  // Arriving from a session that just ended goes straight to that cohort —
  // the guided flow's last step is a payoff, not another picker (`DATA.md#session-order`).
  // Arriving cold shows the picker instead: auto-selecting the most recent
  // cohort answers a question the reader hasn't asked yet.
  //
  // Keyed on the navigation entry rather than on the cohort, for two reasons.
  // The arrival has to win even when some *other* cohort is already selected,
  // or the banner announces one session above another cohort's panels. And the
  // fetch has to be forced: a cohort looked at earlier this run is cached, and
  // the run that just finished is precisely what the cache predates, so
  // the reload shows the reading notice rather than the old numbers.
  const handledArrival = useRef<string | null>(null);
  // A folder is parked here by the arrival and resolved to a session id below,
  // once the cohort's session list exists to resolve it against. Tagged with
  // the cohort it arrived for, which is load-bearing: the resolver runs once in
  // the same commit as the arrival, when `cohortId` is still the PREVIOUS
  // selection and its list is the previous cohort's. Untagged, that pass would
  // consume the folder against the wrong list.
  const pendingFolder = useRef<{
    cohortId: string;
    folder: DiskSession;
  } | null>(null);
  useEffect(() => {
    if (!landing?.cohortId || handledArrival.current === location.key) return;
    // Not marked handled until the socket is up, so a cold start retries
    // instead of dropping the arrival on the floor.
    if (!connected) return;
    handledArrival.current = location.key;
    store.selectCohort(landing.cohortId);
    // The scope is set explicitly, never left alone. `selectCohort` clears it
    // only when the cohort actually changes, so arriving on the cohort you were
    // already looking at would otherwise keep whichever session was filtered —
    // and a Dashboard *cohort* row means the across-session view. A pending
    // folder starts here too and narrows once it resolves, which is also where
    // it should rest if this machine hasn't indexed that folder.
    store.selectSession(landing.sessionId ?? ALL_SESSIONS);
    pendingFolder.current = landing.sessionFolder
      ? { cohortId: landing.cohortId, folder: landing.sessionFolder }
      : null;
    setReveal((n) => n + 1);
    void store.refresh(client, landing.cohortId);
  }, [
    location.key,
    landing?.cohortId,
    landing?.sessionId,
    landing?.sessionFolder,
    connected,
    client,
    store,
  ]);

  // A folder can only become a session id once the cohort's session list is
  // here, which is after the refresh above resolves — so the arrival parks the
  // folder and this picks it up.
  //
  // Cleared on the first attempt either way. A folder another Ephymeris machine
  // wrote has no row on this one until a rescan adopts it (the "not indexed"
  // hint on the Dashboard row), and retrying forever would mean a later manual
  // session pick got yanked back the moment anything refreshed.
  useEffect(() => {
    const pending = pendingFolder.current;
    if (!pending || pending.cohortId !== cohortId || state !== "ready") return;
    pendingFolder.current = null;
    const match = findSessionByFolder(sessions, pending.folder);
    if (match) store.selectSession(match.id);
  }, [sessions, state, cohortId, store]);

  // `version` is what makes an invalidation actionable: it is the only one of
  // these that changes when a cached summary is dropped out from under a
  // dashboard that is already on screen.
  useEffect(() => {
    if (!connected || !cohortId) return;
    void store.load(client, cohortId);
  }, [client, connected, cohortId, store, version]);

  // There is no dashboard-wide task filter (`DATA.md#pooling-across-tasks`). The outcome
  // panels pool every run and disclose the task mix (the strip and the
  // dashed change rules); the panels whose metrics genuinely cannot cross
  // tasks — the strategy planes — scope themselves and offer a panel-local
  // switch. Nothing the archive holds is ever silently hidden.
  const colors = useMemo(
    () => buildAnimalColors(summary?.animals ?? []),
    [summary],
  );
  const revealKey = `${cohortId ?? ""}:${reveal}`;
  const selectedSession = useMemo(
    () =>
      sessionScope === ALL_SESSIONS
        ? null
        : (sessions.find((session) => session.id === sessionScope) ?? null),
    [sessions, sessionScope],
  );
  // Every run in the selected session, whatever task it was on and whether
  // or not it decoded (`session.ts`) — the one list every session-scope panel
  // reads, each scoping itself from there. Fetched once here because
  // selecting a session puts the summary tile, the within-session strategy
  // walk and the learning curves on screen together, and all three want the
  // same `analytics.series` reply.
  const sessionAllRuns = useMemo(
    () =>
      selectedSession && summary
        ? sessionRunsOf(summary, selectedSession.id)
        : NO_RUNS,
    [summary, selectedSession],
  );
  const sessionSeries = useRunSeries(client, sessionAllRuns);

  // The export (`DATA.md#exporting-a-sheet`) composes the very panels above out of these same props,
  // which is what keeps the PNG and the screen from drifting apart. The scope
  // decides which sheet: exporting is a picture of what you are looking at, in
  // the same spirit as the header's "selection is a filter, not navigation".
  const exporter = useExportReport();
  const reportInput = useMemo<ReportInput | null>(
    () =>
      summary
        ? {
            summary,
            colors,
            cohortName: active?.name ?? "All cohorts",
            revealKey,
            session: selectedSession,
            sessionAllRuns,
            sessionSeries,
          }
        : null,
    [
      summary,
      colors,
      active?.name,
      revealKey,
      selectedSession,
      sessionAllRuns,
      sessionSeries,
    ],
  );

  const folderWarning = summary?.warnings.find(
    (w) => w.code === "data-folder-missing",
  );
  const runWarnings = useMemo(
    () =>
      summary?.warnings.filter((w) => w.code !== "data-folder-missing") ?? [],
    [summary],
  );

  async function runRescan() {
    if (!cohortId) return;
    setRescanning(true);
    setRescanNote(null);
    try {
      const result = await rescan(client, cohortId);
      setRescanNote(describeRescan(result));
      setReveal((n) => n + 1);
      await store.refresh(client, cohortId);
    } catch (error) {
      setRescanNote(errorMessage(error));
    } finally {
      setRescanning(false);
    }
  }

  /**
   * The crash-recovery backfill, chained into adoption: a recovered `.json`
   * is by definition a file no run record points at, so without the follow-up
   * rescan it would sit invisible until someone thought to click Rescan —
   * one deliberate action should finish the job it started.
   */
  async function runRecover() {
    if (!cohortId) return;
    setRecovering(true);
    setRescanNote(null);
    try {
      const result = await recover(client, cohortId);
      if (result.recovered > 0) {
        const adopted = await rescan(client, cohortId);
        setRescanNote(`${describeRecover(result)} ${describeRescan(adopted)}`);
        setReveal((n) => n + 1);
        await store.refresh(client, cohortId);
      } else {
        setRescanNote(describeRecover(result));
      }
    } catch (error) {
      setRescanNote(errorMessage(error));
    } finally {
      setRecovering(false);
    }
  }

  // Group names for the tidy preview's "ran Morning, Afternoon" lines.
  const groupNames = useMemo(
    () => new Map((summary?.groups ?? []).map((g) => [g.id, g.name])),
    [summary],
  );

  /** The tidy is applied: the merged and removed sessions leave the rail. */
  async function afterTidy(result: TidyPlan) {
    setTidyOpen(false);
    setRescanNote(describeTidy(result));
    if (!cohortId) return;
    // A selected session may just have been folded into another.
    store.selectSession(ALL_SESSIONS);
    setReveal((n) => n + 1);
    await store.refresh(client, cohortId);
  }

  /*
   * The cohort list is the landing state; a cohort is only chosen deliberately.
   *
   * A list, not the 3D browser `/cohorts` uses: picking which cohort to read is
   * a list choice, and the world disc on each row keeps the identity. Tuning a
   * world belongs where the library is managed, one tab over. The sky stays
   * dimmed (`DENSE_SKY_OPACITY`) — the landing is a display surface like the
   * dashboard it opens.
   */
  if (!cohortId) {
    return (
      <div className="relative h-full">
        <SkyBackdrop opacity={DENSE_SKY_OPACITY} />

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="pointer-events-none absolute inset-0"
        >
          <div className="pointer-events-auto absolute inset-x-8 top-4 bottom-6 flex max-w-[820px] flex-col">
            <h1 className="font-display text-[22px] text-starlight">Analytics</h1>
            <p className="mt-1 text-[12px] leading-relaxed text-static">
              Pick a cohort to study its recorded sessions.
            </p>
            {!connected && (
              <Notice>
                Waiting for the backend — Analytics reads recorded sessions
                from it.
              </Notice>
            )}
            {connected && pickable.length === 0 && (
              <Notice>
                No cohorts yet — Analytics reads sessions recorded against one.
              </Notice>
            )}
            {connected && pickable.length > 0 && (
              <div className="mt-5 flex min-h-0 flex-col">
                <CohortManifest
                  cohorts={pickable}
                  onPick={(id) => {
                    setReveal((n) => n + 1);
                    store.selectCohort(id);
                  }}
                />
              </div>
            )}
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    // Every route sits on the rig's sky, dimmed here so a drifting nebula never
    // competes with a learning curve (`SkyBackdrop`). It is
    // mounted rather than omitted because a route with no constellation is the
    // one thing that releases the shared canvas.
    <div className="relative h-full">
      <SkyBackdrop opacity={DENSE_SKY_OPACITY} />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        {/* Wider than the app's other pages: this is the large display, and
            its first row carries the roster, the strategy plane and the trend
            side by side. */}
        <section className="pointer-events-auto mx-auto max-w-[1440px] px-8 py-8">
          <div className="flex flex-wrap items-start justify-between gap-3">
            {/* `items-start`, not centre: the text block is three lines here
                (title, breadcrumb, fact) and a chip centred on it sat beside
                the breadcrumb. The chip is centred on the *title* instead. */}
            <div className="flex items-start gap-3">
              <span className="-mt-1 flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
                <ChartLine
                  size={18}
                  strokeWidth={1.75}
                  className="text-pulsar"
                />
              </span>
              <div className="min-w-0">
                {/* What the display is showing, in its own idiom — and the
                    link it is reading over, Ion because that is exactly the
                    one thing Ion means (`ARCHITECTURE.md#theme`). */}
                <p className="flex items-center gap-2 font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">
                  <span>
                    Telemetry ·{" "}
                    {selectedSession
                      ? `${selectedSession.prefixName}_${selectedSession.sessionNumber}`
                      : "all sessions"}
                  </span>
                  <span className="flex items-center gap-1">
                    <span
                      className={`size-1.5 rounded-full ${connected ? "bg-ion" : "bg-halo"}`}
                      aria-hidden
                    />
                    {connected ? "link" : "no link"}
                  </span>
                </p>
                <h1 className="font-display text-[22px] text-starlight">
                  Analytics
                </h1>
                <ChangeCohort
                  name={active?.name ?? "All cohorts"}
                  // The cohort's world, as the list drew it — so the
                  // breadcrumb reads "you are on this planet" and not just
                  // a name.
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
                <ArchiveFact
                  sessions={sessions}
                  summary={summary}
                  loading={state === "loading"}
                  folderMissing={Boolean(folderWarning)}
                />
              </div>
            </div>
            {/* No Task or Metric selector. The panels below show the whole
                archive and scope themselves where a task boundary is real
                (`DATA.md#pooling-across-tasks`) — the reader never has to maintain a filter to be sure
                they are seeing everything. */}
            <div className="flex items-center gap-2">
              {/* First in the row: the only button here about *where the data
                  lives* rather than about maintaining the index. The path
                  rides the summary — the same string the folder-missing
                  warning names. */}
              {summary && (
                <FolderButton
                  path={summary.dataFolder}
                  label="Data folder"
                />
              )}
              <Button
                variant="outline"
                onClick={() => void runRescan()}
                disabled={!connected || !cohortId || rescanning || recovering}
                title="Look for session files no run record points at"
              >
                <RefreshCw size={13} strokeWidth={1.75} />
                {rescanning ? "Scanning…" : "Rescan"}
              </Button>
              <Button
                variant="outline"
                onClick={() => void runRecover()}
                disabled={!connected || !cohortId || rescanning || recovering}
                title="Rebuild .json/.mat from write-ahead .tsv files a crash left behind"
              >
                <ArchiveRestore size={13} strokeWidth={1.75} />
                {recovering ? "Recovering…" : "Recover"}
              </Button>
              <Button
                variant="outline"
                onClick={() => setTidyOpen(true)}
                disabled={!connected || !cohortId || rescanning || recovering}
                title="Merge one session's split records and remove empty ones — shows what it will do first"
              >
                <Combine size={13} strokeWidth={1.75} />
                Tidy records
              </Button>
              {/* One button, following the scope, rather than two side by side:
              which sheet you get is already answered by what you are looking
              at, and the label says so outright. */}
              <Button
                variant="outline"
                onClick={() => {
                  if (reportInput)
                    void exporter.run(reportInput, reportFilename(reportInput));
                }}
                disabled={
                  !reportInput || exporter.busy || rescanning || recovering
                }
                title={
                  selectedSession
                    ? "Save this session's panels as one PNG"
                    : "Save the across-session panels as one PNG"
                }
              >
                <Download size={13} strokeWidth={1.75} />
                {exporter.busy
                  ? "Exporting…"
                  : selectedSession
                    ? "Export session PNG"
                    : "Export cohort PNG"}
              </Button>
            </div>
          </div>

          {exporter.portal}

          {/* Every message the page can carry is one `Strip`: an icon, a
              tone, a line. They used to be five shapes — a green button, a
              red box, two plain paragraphs and a bare mono line — and the
              reader had to learn each one to know whether it mattered. */}
          {banner && (
            <Strip tone="ok" icon={CircleCheck} onDismiss={() => setBanner(null)}>
              {banner} ended and saved.
            </Strip>
          )}

          {!connected && (
            <Strip tone="neutral" icon={CircleAlert}>
              Waiting for the backend — Analytics reads recorded sessions from
              it.
            </Strip>
          )}

          {connected && loadError && (
            <Strip tone="error" icon={CircleAlert}>
              {loadError}
            </Strip>
          )}

          {connected && state === "loading" && (
            <Strip tone="neutral" icon={Loader2} spin>
              {progress
                ? `Reading session files — ${progress.done} of ${progress.total}…`
                : "Loading…"}
            </Strip>
          )}

          {cohortId && (
            <TidyRecords
              open={tidyOpen}
              cohortId={cohortId}
              groupNames={groupNames}
              onClose={() => setTidyOpen(false)}
              onDone={(result) => void afterTidy(result)}
            />
          )}
          {rescanNote && (
            <Strip tone="neutral" icon={Info} onDismiss={() => setRescanNote(null)}>
              {rescanNote}
            </Strip>
          )}

          {connected && summary && (
            // The whole dashboard body arrives on one summary reply, so it is
            // the largest single mount in the app — animated, or a cohort
            // selection slams every panel in on the same frame.
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={springPanel}
              className="mt-5 flex flex-col gap-3"
            >
              <SessionRail
                sessions={sessions}
                summary={summary}
                selected={sessionScope}
              />

              {/* A cohort whose folder is gone isn't a damaged run — it's the whole
              archive being unreachable, and calling it "1 run could not be read"
              would point the reader at exactly the wrong thing. */}
              {folderWarning && (
                <p className="px-1 text-[11px] leading-relaxed text-static">
                  <span style={{ color: "var(--color-status-warning)" }}>
                    Can&rsquo;t reach this cohort&rsquo;s data folder
                  </span>{" "}
                  — <span className="font-mono">{folderWarning.message}</span>.
                  Anything below is the last successful read. Reconnect the
                  drive, or change the folder in the cohort editor.
                </p>
              )}

              {runWarnings.length > 0 && (
                <p className="px-1 text-[11px] leading-relaxed text-static">
                  <span style={{ color: "var(--color-status-warning)" }}>
                    {runWarnings.length} run
                    {runWarnings.length === 1 ? "" : "s"} could not be read
                  </span>{" "}
                  — everything else is unaffected. {runWarnings[0]!.message}
                </p>
              )}

              {/* Selecting a session opens it up, and the summary answers
              first: it lands directly under the rail that made the selection,
              not below three screens of cohort-scale panels. The cohort views
              compare sessions; this one is the inside of a single one. */}
              {selectedSession && (
                <h2 className="telemetry-section mt-1.5">Inside the session</h2>
              )}
              <AnimatePresence mode="wait">
                {selectedSession && (
                  <SessionSummary
                    key={selectedSession.id}
                    summary={summary}
                    colors={colors}
                    session={selectedSession}
                    runs={sessionAllRuns}
                    series={sessionSeries}
                    revealKey={revealKey}
                  />
                )}
              </AnimatePresence>

              {/* Across sessions: the roster, the strategy plane and the
              accuracy trend in one row, then effort and the outcome mix
              (`CohortTrends`). Within a session, the rail sits beside that
              session's strategy walk and rolling accuracy. */}
              {sessionScope === ALL_SESSIONS ? (
                <>
                  <h2 className="telemetry-section mt-1.5">Across sessions</h2>
                  <CohortTrends summary={summary} colors={colors} revealKey={revealKey} />
                </>
              ) : (
                // The across-session row's proportions (`CohortTrends`): the
                // roster, the walk on a square plane of a fixed width, and the
                // rolling curve taking the rest. `items-start`: the tiles must
                // not share a height, or opening one's "how to read this"
                // would stretch the other's chart.
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-[208px_minmax(240px,280px)_minmax(0,1fr)] 2xl:grid-cols-[224px_minmax(300px,360px)_minmax(0,1fr)] xl:items-start">
                  <div className="xl:relative xl:self-stretch">
                    <AnimalRail summary={summary} colors={colors} scroll="xl" />
                  </div>
                  <div className="w-full max-w-[420px] min-w-0 xl:max-w-none">
                    <SessionStrategy
                      summary={summary}
                      colors={colors}
                      runs={sessionAllRuns}
                      series={sessionSeries}
                      revealKey={revealKey}
                    />
                  </div>
                  <LearningCurves colors={colors} sessionRuns={sessionAllRuns} series={sessionSeries} />
                </div>
              )}

              <Footnote
                summary={summary}
                cohortName={active?.name ?? ""}
                scope={sessionScope}
              />
            </motion.div>
          )}
        </section>
      </motion.div>
    </div>
  );
}

/**
 * What the archive walk found, in the order that matters to the reader.
 *
 * An unreachable folder comes first and alone: every other number is zero
 * *because* of it, so reporting "scanned 0 files" as though the archive were
 * empty would be actively misleading. Duplicates are reported rather than
 * quietly dropped — a hand-managed archive that keeps a consolidated copy
 * beside the originals is normal, and silently halving a file count is the
 * kind of thing that makes someone doubt the whole panel.
 */
function describeRescan(result: RescanResult): string {
  if (result.folderMissing) {
    return `Can't reach ${result.dataFolder} — nothing was scanned. Reconnect the drive, or change this cohort's data folder.`;
  }
  const parts = [
    `Scanned ${result.scanned} file${result.scanned === 1 ? "" : "s"}`,
  ];
  if (result.adopted > 0) {
    parts.push(`adopted ${result.adopted} that no run record pointed at`);
  }
  if (result.duplicates > 0) {
    parts.push(
      `skipped ${result.duplicates} duplicate cop${result.duplicates === 1 ? "y" : "ies"} of runs already found`,
    );
  }
  // Deletions are stated, always. A reconciliation that quietly dropped rows
  // is indistinguishable from a walk that failed to find them, and this is the
  // one number in the note that the operator can't recover by clicking again.
  const pruned = prunedRecords(result.pruned);
  if (pruned) parts.push(pruned);
  const unmatched = result.orphans.filter((o) => o.animalId === null).length;
  if (unmatched > 0) {
    parts.push(
      `${unmatched} matched no animal on the roster and were left alone`,
    );
  }
  // A correction the operator can't see is one they can't check.
  const byName = result.orphans.filter(
    (o) => o.animalSource === "filename",
  ).length;
  if (byName > 0) {
    parts.push(
      `${byName} named an animal the roster doesn't have and ${byName === 1 ? "was" : "were"} matched on ${byName === 1 ? "its" : "their"} filename instead`,
    );
  }
  if (parts.length === 1)
    return `${parts[0]} — everything on disk is already indexed.`;
  return `${parts.join("; ")}.`;
}

/**
 * The prune clause of the rescan note (`DATA.md#pruning`), or null when nothing
 * was removed — which is the overwhelmingly common case and doesn't deserve a
 * sentence.
 *
 * Says **records**, and says it about the files rather than about the data: the
 * rescan removes this app's bookkeeping and has never touched the archive, and
 * an operator reading "removed 4 sessions" with no qualifier has every reason
 * to wonder which of the two just happened.
 */
function prunedRecords(pruned: RescanPruned): string | null {
  const parts: string[] = [];
  if (pruned.runs > 0) parts.push(`${pruned.runs} run${plural(pruned.runs)}`);
  if (pruned.adopted > 0) parts.push(`${pruned.adopted} adopted run${plural(pruned.adopted)}`);
  if (pruned.sessions > 0) {
    parts.push(`${pruned.sessions} session${plural(pruned.sessions)}`);
  }
  if (parts.length === 0) return null;
  return `dropped the records of ${joinList(parts)} whose files are no longer on disk`;
}

function plural(n: number): string {
  return n === 1 ? "" : "s";
}

function joinList(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * The recovery half of the note. Failures are named per file — an operator
 * running this at all is cleaning up after a crash, and "1 of 2 failed" with
 * no path would send them digging through the sidecar log for which one.
 */
function describeRecover(result: RecoverResult): string {
  if (result.folderMissing) {
    return `Can't reach ${result.dataFolder} — nothing was scanned. Reconnect the drive, or change this cohort's data folder.`;
  }
  if (result.scanned === 0) {
    return "No orphaned .tsv files — every write-ahead log already has its .json.";
  }
  const parts = [
    `Recovered ${result.recovered} of ${result.scanned} orphaned .tsv file${result.scanned === 1 ? "" : "s"}`,
  ];
  for (const entry of result.entries) {
    if (entry.status === "failed") {
      parts.push(`${entry.tsvPath}: ${entry.reason ?? "failed"}`);
    }
  }
  return `${parts.join("; ")}.`;
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="mt-4 max-w-prose text-[13px] leading-relaxed text-static">
      {children}
    </p>
  );
}

/**
 * The archive in one mono line under the breadcrumb — the Rig and Task tabs'
 * fact line, answered with numbers: how many sessions, how many animals, when
 * the last one ran.
 *
 * Coloured by whether the numbers can be trusted, not by how good they are: the
 * warning tone while the cohort's folder is out of reach, because every figure
 * under it is then the last successful read (`DATA.md#caching`); quiet otherwise. Not Ion
 * when healthy — a readable archive is the normal state, and status colour is
 * for the exceptions.
 */
function ArchiveFact({
  sessions,
  summary,
  loading,
  folderMissing,
}: {
  sessions: SessionListItem[];
  summary: AnalyticsSummary | null;
  loading: boolean;
  folderMissing: boolean;
}) {
  const muted = "mt-1 font-mono text-[10px] text-static/70";
  if (!summary) {
    return loading ? <p className={muted}>reading the archive…</p> : null;
  }
  // By ordinal, never by list position or session number — `ordinal` is the
  // chronological rank and the number is free text (`SessionListItem`).
  const last = sessions.reduce<SessionListItem | null>(
    (best, session) =>
      best === null || session.ordinal > best.ordinal ? session : best,
    null,
  );
  const n = (count: number, word: string) =>
    `${count} ${word}${count === 1 ? "" : "s"}`;
  const parts = [n(sessions.length, "session"), n(summary.animals.length, "animal")];
  if (summary.groups.length > 1) parts.push(n(summary.groups.length, "group"));
  parts.push(last ? `last ran ${last.date}` : "nothing recorded yet");
  if (folderMissing) parts.push("folder unreachable");
  return (
    <p
      className={muted}
      style={folderMissing ? { color: "var(--color-status-warning)" } : undefined}
    >
      {parts.join(" · ")}
    </p>
  );
}

/**
 * One message strip: an icon, a tone, a line — and `dismiss` when the reader
 * can put it away. The tone is the state (Ion for a session safely on disk,
 * the error tone for a summary that could not be read) and nothing else; a
 * rescan report and an export note are facts, and stay in static.
 */
function Strip({
  tone,
  icon: Icon,
  spin = false,
  onDismiss,
  children,
}: {
  tone: "ok" | "error" | "neutral";
  icon: LucideIcon;
  spin?: boolean;
  onDismiss?: () => void;
  children: ReactNode;
}) {
  const color = {
    ok: "var(--color-status-ok)",
    error: "var(--color-status-error)",
    neutral: "var(--color-static)",
  }[tone];
  const className =
    "mt-3 flex w-full items-center gap-2 rounded-sm border border-halo bg-nebula/60 px-3 py-2 text-left font-mono text-[11px] leading-relaxed";
  const body = (
    <>
      <Icon
        size={14}
        strokeWidth={1.75}
        className={`shrink-0 ${spin ? "animate-spin" : ""}`}
      />
      <span className="min-w-0 flex-1">{children}</span>
      {onDismiss && <span className="ml-auto shrink-0 text-static/70">dismiss</span>}
    </>
  );
  return onDismiss ? (
    <button type="button" onClick={onDismiss} className={className} style={{ color }}>
      {body}
    </button>
  ) : (
    <div className={className} style={{ color }}>
      {body}
    </div>
  );
}
