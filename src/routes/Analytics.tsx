import { AnimatePresence, motion } from "framer-motion";
import { ArchiveRestore, ChartLine, CircleAlert, CircleCheck, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";

import { AnimalRail } from "@/components/analytics/AnimalRail";
import { ChangeCohort, CohortLanding } from "@/components/analytics/CohortLanding";
import { CohortHeatmap } from "@/components/analytics/CohortHeatmap";
import { EffortTrend } from "@/components/analytics/EffortTrend";
import { LearningCurves } from "@/components/analytics/LearningCurves";
import { OutcomeMix } from "@/components/analytics/OutcomeMix";
import { ResponseTrend } from "@/components/analytics/ResponseTrend";
import { RewardedTrend } from "@/components/analytics/RewardedTrend";
import { SessionRail } from "@/components/analytics/SessionRail";
import { SessionStrategy } from "@/components/analytics/SessionStrategy";
import { SessionSummary } from "@/components/analytics/SessionSummary";
import { StrategySpace } from "@/components/analytics/StrategySpace";
import { Button, Select } from "@/components/common/controls";
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
  RecoverResult,
  RescanResult,
  RunSummary,
} from "@/lib/analytics/types";
import { buildAnimalColors, dominantProfile, runsInProfile } from "@/lib/analytics/view";
import { useCohorts } from "@/lib/cohorts/context";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/** Stable empty reference, so the profile memo isn't invalidated every render. */
const NO_PROFILES: AnalyticsSummary["profileGroups"] = [];
const NO_RUNS: RunSummary[] = [];

/**
 * The Analytics dashboard — the "Observatory" (`analytics.md` §2).
 *
 * One route, no tabs. Cohort, session and animal are persistent selectors, and
 * **selection is a filter, not navigation**: picking a session narrows every
 * panel rather than swapping the view, and hovering an animal highlights its
 * curve, its heatmap row and its strategy trail at once.
 */
export function Analytics() {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();
  const cohorts = useCohorts();
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
  const [rescanNote, setRescanNote] = useState<string | null>(null);
  const [metricId, setMetricId] = useState<string | null>(null);
  const [profileHash, setProfileHash] = useState<string | null>(null);
  // Bumped whenever the data underneath changes identity — a cohort swap or a
  // rescan. Panels key their draw-on animations off it, so a reveal replays
  // for genuinely new data and not for a hover.
  const [reveal, setReveal] = useState(0);

  // §2.5 — ending a session lands here with that cohort and session already
  // selected, so the guided flow's last step is a payoff rather than an
  // acknowledgement.
  const landing = location.state as
    | { endedSession?: string | null; cohortId?: string; sessionId?: string }
    | null;
  const [banner, setBanner] = useState<string | null>(landing?.endedSession ?? null);

  const active = cohorts.find((cohort) => cohort.id === cohortId) ?? null;
  const connected = status === "connected";

  // Arriving from a session that just ended goes straight to that cohort —
  // the guided flow's last step is a payoff, not another picker (§2.5).
  // Arriving cold shows the picker instead: auto-selecting the most recent
  // cohort answers a question the reader hasn't asked yet.
  //
  // Keyed on the navigation entry rather than on the cohort, for two reasons.
  // The arrival has to win even when some *other* cohort is already selected,
  // or the banner announces one session above another cohort's panels. And the
  // fetch has to be forced: a cohort looked at earlier this run is cached, and
  // the run that just finished is precisely what the cache predates. §2.4 —
  // the reload shows the reading notice rather than the old numbers.
  const handledArrival = useRef<string | null>(null);
  useEffect(() => {
    if (!landing?.cohortId || handledArrival.current === location.key) return;
    // Not marked handled until the socket is up, so a cold start retries
    // instead of dropping the arrival on the floor.
    if (!connected) return;
    handledArrival.current = location.key;
    store.selectCohort(landing.cohortId);
    if (landing.sessionId) store.selectSession(landing.sessionId);
    setMetricId(null);
    setProfileHash(null);
    setReveal((n) => n + 1);
    void store.refresh(client, landing.cohortId);
  }, [location.key, landing?.cohortId, landing?.sessionId, connected, client, store]);

  // `version` is what makes an invalidation actionable: it is the only one of
  // these that changes when a cached summary is dropped out from under a
  // dashboard that is already on screen.
  useEffect(() => {
    if (!connected || !cohortId) return;
    void store.load(client, cohortId);
  }, [client, connected, cohortId, store, version]);

  // §4.3 — every panel is scoped to one task profile, because metrics from
  // different tasks are not comparable even when they share an axis count.
  // The dominant profile is only the default: a cohort that ran shaping and
  // then discrimination has both, and which one you want to look at is a
  // question only the reader can answer.
  const profiles = summary?.profileGroups ?? NO_PROFILES;
  const profile = useMemo(
    () =>
      profiles.find((group) => group.hash === profileHash) ?? dominantProfile(summary),
    [profiles, profileHash, summary],
  );
  const colors = useMemo(() => buildAnimalColors(summary?.animals ?? []), [summary]);
  const activeMetric = metricId ?? profile?.metrics[0]?.id ?? null;
  const revealKey = `${cohortId ?? ""}:${reveal}`;
  const selectedSession = useMemo(
    () =>
      sessionScope === ALL_SESSIONS
        ? null
        : (sessions.find((session) => session.id === sessionScope) ?? null),
    [sessions, sessionScope],
  );
  // Fetched once here rather than in each panel: selecting a session puts the
  // summary tile, the within-session strategy walk and the learning curves on
  // screen together, and all three want the same `analytics.series` reply.
  const sessionRuns = useMemo(
    () =>
      selectedSession && summary
        ? runsInProfile(summary.runs, profile).filter(
            (run) => run.sessionId === selectedSession.id,
          )
        : NO_RUNS,
    [summary, profile, selectedSession],
  );
  const sessionSeries = useRunSeries(client, sessionRuns);

  const folderWarning = summary?.warnings.find((w) => w.code === "data-folder-missing");
  const runWarnings = useMemo(
    () => summary?.warnings.filter((w) => w.code !== "data-folder-missing") ?? [],
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

  // The picker is the landing state; a cohort is only chosen deliberately.
  if (!cohortId) {
    return (
      <motion.section className="mx-auto max-w-6xl px-8 py-8">
        {!connected ? (
          <Notice>
            Waiting for the backend — Analytics reads recorded sessions from it.
          </Notice>
        ) : (
          <CohortLanding
            cohorts={cohorts}
            onPick={(next) => {
              setMetricId(null);
              setProfileHash(null);
              setReveal((n) => n + 1);
              store.selectCohort(next);
            }}
          />
        )}
      </motion.section>
    );
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-6xl px-8 py-8"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
            <ChartLine size={18} strokeWidth={1.75} className="text-pulsar" />
          </span>
          <div>
            <h1 className="font-display text-[22px] text-starlight">Analytics</h1>
            <ChangeCohort
              name={active?.name ?? "All cohorts"}
              onBack={() => {
                setMetricId(null);
                setProfileHash(null);
                store.selectCohort(null);
              }}
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {profiles.length > 1 && (
            <Select
              label="Task"
              value={profile?.hash ?? ""}
              options={profiles.map((group) => ({
                value: group.hash,
                label: `${group.taskName ?? "Unnamed task"} · ${group.runCount}`,
              }))}
              onChange={(next) => {
                // Metrics are declared per task, so the current selection
                // usually doesn't exist on the incoming one.
                setMetricId(null);
                setProfileHash(next);
              }}
            />
          )}
          {profile && profile.metrics.length > 1 && (
            <Select
              label="Metric"
              value={activeMetric ?? ""}
              options={profile.metrics.map((metric) => ({
                value: metric.id,
                label: metric.label,
              }))}
              onChange={(next) => setMetricId(next)}
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
        </div>
      </div>

      {banner && (
        <button
          type="button"
          onClick={() => setBanner(null)}
          className="mt-4 flex w-full items-center gap-1.5 rounded-sm border border-halo px-3 py-2 text-left font-mono text-[12px]"
          style={{ color: "var(--color-status-ok)" }}
        >
          <CircleCheck size={14} strokeWidth={1.75} className="shrink-0" />
          {banner} ended and saved.
          <span className="ml-auto text-static/70">dismiss</span>
        </button>
      )}

      {!connected && (
        <Notice>
          Waiting for the backend — Analytics reads recorded sessions from it.
        </Notice>
      )}

      {connected && loadError && (
        <div
          className="mt-4 flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
          style={{ color: "var(--color-status-error)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} />
          {loadError}
        </div>
      )}

      {connected && state === "loading" && (
        <Notice>
          {progress
            ? `Reading session files — ${progress.done} of ${progress.total}…`
            : "Loading…"}
        </Notice>
      )}

      {rescanNote && <p className="mt-3 font-mono text-[11px] text-static">{rescanNote}</p>}

      {connected && summary && (
        <div className="mt-5 flex flex-col gap-3">
          <SessionRail sessions={sessions} summary={summary} selected={sessionScope} />

          {/* A cohort whose folder is gone isn't a damaged run — it's the whole
              archive being unreachable, and calling it "1 run could not be read"
              would point the reader at exactly the wrong thing. */}
          {folderWarning && (
            <p className="px-1 text-[11px] leading-relaxed text-static">
              <span style={{ color: "var(--color-status-warning)" }}>
                Can&rsquo;t reach this cohort&rsquo;s data folder
              </span>{" "}
              — <span className="font-mono">{folderWarning.message}</span>.
              Anything below is the last successful read. Reconnect the drive, or
              change the folder in the cohort editor.
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

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,224px)_minmax(0,1fr)]">
            <AnimalRail
              summary={summary}
              profile={profile}
              colors={colors}
              metricId={activeMetric}
            />
            <div className="flex min-w-0 flex-col gap-3">
              <div className="grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2">
                {/* §4.4 — the two strategy panels share one plane and swap,
                    never coexist: a line in one spans weeks and a line in the
                    other spans an hour, and the frame cannot tell them apart. */}
                {selectedSession ? (
                  <SessionStrategy
                    summary={summary}
                    profile={profile}
                    colors={colors}
                    runs={sessionRuns}
                    series={sessionSeries}
                    revealKey={revealKey}
                  />
                ) : (
                  <StrategySpace summary={summary} profile={profile} colors={colors} />
                )}
                <LearningCurves
                  summary={summary}
                  profile={profile}
                  colors={colors}
                  sessionScope={sessionScope}
                  series={sessionSeries}
                />
              </div>
              {/* The outcome trends are across-session by nature: one session
                  has a single pooled figure, and the summary below shows that
                  per animal instead of flattening it to a dot. All three share
                  x slots (`sessionOutcomePoints`), so a session sits above
                  itself in every panel. */}
              {sessionScope === ALL_SESSIONS && (
                <>
                  <RewardedTrend
                    summary={summary}
                    profile={profile}
                    colors={colors}
                    revealKey={revealKey}
                  />
                  {/* Directly below rewarded accuracy, and full width like it:
                      the two share x slots and a denominator, so the gap
                      between the curves is the hold-failure rate — a reading
                      that only survives if a session sits above itself and
                      both plots are the same shape. */}
                  <ResponseTrend
                    summary={summary}
                    profile={profile}
                    colors={colors}
                    revealKey={revealKey}
                  />
                  <div className="grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2">
                    <EffortTrend summary={summary} profile={profile} revealKey={revealKey} />
                    <OutcomeMix summary={summary} profile={profile} revealKey={revealKey} />
                  </div>
                </>
              )}
              <CohortHeatmap
                summary={summary}
                profile={profile}
                metricId={activeMetric}
                sessionScope={sessionScope}
                revealKey={revealKey}
              />
            </div>
          </div>

          {/* Selecting a session opens it up: the cohort views compare
              sessions, this one is the inside of a single one. */}
          <AnimatePresence mode="wait">
            {selectedSession && (
              <SessionSummary
                key={selectedSession.id}
                summary={summary}
                profile={profile}
                colors={colors}
                session={selectedSession}
                runs={sessionRuns}
                series={sessionSeries}
                revealKey={revealKey}
              />
            )}
          </AnimatePresence>

          <Footnote summary={summary} cohortName={active?.name ?? ""} scope={sessionScope} />
        </div>
      )}
    </motion.section>
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
  const parts = [`Scanned ${result.scanned} file${result.scanned === 1 ? "" : "s"}`];
  if (result.adopted > 0) {
    parts.push(`adopted ${result.adopted} that no run record pointed at`);
  }
  if (result.duplicates > 0) {
    parts.push(
      `skipped ${result.duplicates} duplicate cop${result.duplicates === 1 ? "y" : "ies"} of runs already found`,
    );
  }
  const unmatched = result.orphans.filter((o) => o.animalId === null).length;
  if (unmatched > 0) {
    parts.push(`${unmatched} matched no animal on the roster and were left alone`);
  }
  // A correction the operator can't see is one they can't check.
  const byName = result.orphans.filter((o) => o.animalSource === "filename").length;
  if (byName > 0) {
    parts.push(
      `${byName} named an animal the roster doesn't have and ${byName === 1 ? "was" : "were"} matched on ${byName === 1 ? "its" : "their"} filename instead`,
    );
  }
  if (parts.length === 1) return `${parts[0]} — everything on disk is already indexed.`;
  return `${parts.join("; ")}.`;
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

function Footnote({
  summary,
  cohortName,
  scope,
}: {
  summary: AnalyticsSummary;
  cohortName: string;
  scope: string;
}) {
  const fallback = summary.runs.filter((run) => run.profileSource === "sketch-current").length;
  return (
    <p className="px-1 font-mono text-[10px] leading-relaxed text-static/70">
      {cohortName} · {summary.counts.decoded} of {summary.counts.runs} runs scored ·{" "}
      {scope === ALL_SESSIONS ? "all sessions" : "one session"} · fewer than{" "}
      {summary.minCountedTrials} scored trials shows as a count, not a probability
      {fallback > 0 && (
        <>
          {" · "}
          <span style={{ color: "var(--color-status-warning)" }}>
            {fallback} run{fallback === 1 ? "" : "s"} decoded with the current
            task.json, which may have changed since
          </span>
        </>
      )}
    </p>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return <p className="mt-4 max-w-prose text-[13px] leading-relaxed text-static">{children}</p>;
}
