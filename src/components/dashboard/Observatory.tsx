import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { useEffect, useMemo, useReducer, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { TelemetryPanel } from "@/components/common/TelemetryPanel";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { recentSessions as fetchRecentSessions } from "@/lib/analytics/commands";
import { useAnalyticsStore } from "@/lib/analytics/context";
import type { DiskSession } from "@/lib/analytics/types";
import { useActiveCohorts, useCohortsLoaded } from "@/lib/cohorts/context";
import { springSnappy } from "@/lib/motion";
import { useRunningSession } from "@/lib/sessions/context";
import { useSidecar } from "@/lib/ws/context";

type Tab = "cohorts" | "accuracy" | "recent";

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: "cohorts", label: "Cohorts" },
  { id: "accuracy", label: "Accuracy" },
  { id: "recent", label: "Recent" },
];

/** Rows a tab shows before deferring to its full page. */
const MAX_ROWS = 6;

/**
 * The lab at a glance (`USER-GUIDE.md#a-tour-of-the-app`): the cohorts, their
 * reward accuracy over sessions, and the latest sessions on disk — three
 * readings of one archive, so one panel turned between them rather than three
 * cards stacked. The indicator travels between tabs; arrow keys move it.
 *
 * Every row opens what it names: a cohort its page, a sparkline its Analytics,
 * a recent session its place in that cohort's history.
 */
export function Observatory() {
  const navigate = useNavigate();
  const cohorts = useActiveCohorts();
  const loaded = useCohortsLoaded();
  const series = useCohortRewardSeries();
  const recent = useRecentSessions();
  const [tab, setTab] = useState<Tab>("cohorts");
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKey(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const index = TABS.findIndex((t) => t.id === tab);
    const next = (index + step + TABS.length) % TABS.length;
    const target = TABS[next];
    if (!target) return;
    setTab(target.id);
    refs.current[next]?.focus();
  }

  const destination: Record<Tab, () => void> = {
    cohorts: () => navigate("/cohorts"),
    accuracy: () => navigate("/analytics"),
    recent: () => navigate("/analytics"),
  };

  return (
    <TelemetryPanel
      name="Observatory"
      note="the archive"
      right={
        <button
          type="button"
          onClick={destination[tab]}
          className="flex items-center gap-1 font-mono text-[10px] text-static transition-colors hover:text-starlight"
        >
          {tab === "cohorts" ? "all cohorts" : "analytics"}
          <ArrowRight size={10} strokeWidth={1.75} />
        </button>
      }
    >
      <div
        role="tablist"
        aria-label="Observatory"
        onKeyDown={onKey}
        className="relative mb-1.5 grid grid-cols-3 border-b border-halo/70"
      >
        {TABS.map((t, i) => {
          const active = t.id === tab;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="tab"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(t.id)}
              className={`relative pt-1 pb-1.5 font-mono text-[9.5px] tracking-[0.16em] uppercase transition-colors focus:outline-none focus-visible:text-starlight ${
                active ? "text-starlight" : "text-static/70 hover:text-starlight"
              }`}
            >
              {t.label}
              {active && (
                <motion.span
                  layoutId="observatory-tab"
                  transition={springSnappy}
                  className="absolute inset-x-3 -bottom-px h-px bg-pulsar"
                />
              )}
            </button>
          );
        })}
      </div>

      <div role="tabpanel" className="relative min-h-[132px]">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={springSnappy}
            className="flex flex-col"
          >
            {tab === "cohorts" &&
              (loaded && cohorts.length === 0 ? (
                <Empty>No cohorts yet — create one to start recording sessions.</Empty>
              ) : (
                cohorts.slice(0, MAX_ROWS).map((cohort) => (
                  <Row key={cohort.id} onClick={() => navigate(`/cohorts/${cohort.id}`)}>
                    <PlanetDisc cohortId={cohort.id} appearance={cohort.appearance} size={16} />
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-starlight">{cohort.name}</span>
                    <span className="shrink-0 font-mono text-[10.5px] text-static">
                      {cohort.animalCount} animal{cohort.animalCount === 1 ? "" : "s"} · {cohort.groupCount} group
                      {cohort.groupCount === 1 ? "" : "s"}
                    </span>
                  </Row>
                ))
              ))}

            {tab === "accuracy" &&
              (series.length === 0 ? (
                <Empty>Cohort accuracy will chart here once sessions are recorded.</Empty>
              ) : (
                series.slice(0, MAX_ROWS).map((cohort) => (
                  <Row key={cohort.id} onClick={() => navigate("/analytics", { state: { cohortId: cohort.id } })}>
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-starlight">{cohort.name}</span>
                    {cohort.values.length === 0 ? (
                      <span className="shrink-0 font-mono text-[10px] text-static/60">no scored sessions</span>
                    ) : (
                      <>
                        <Sparkline
                          values={cohort.values}
                          title={`${cohort.name}: reward accuracy across ${cohort.values.length} session${cohort.values.length === 1 ? "" : "s"}`}
                        />
                        <span className="w-9 shrink-0 text-right font-mono text-[11px] text-starlight tabular-nums">
                          {Math.round((cohort.values[cohort.values.length - 1] ?? 0) * 100)}%
                        </span>
                      </>
                    )}
                  </Row>
                ))
              ))}

            {tab === "recent" &&
              (recent.loaded && recent.sessions.length === 0 ? (
                <Empty>No sessions recorded yet.</Empty>
              ) : (
                recent.sessions.map((session) => (
                  <Row
                    key={session.folderPath}
                    // The folder, not a session id: these rows come from a walk
                    // of directory names (`analytics.recentSessions`), and one
                    // this machine hasn't indexed has no id to send.
                    onClick={() =>
                      navigate("/analytics", { state: { cohortId: session.cohortId, sessionFolder: session } })
                    }
                  >
                    <span className="shrink-0 font-mono text-[10.5px] text-static tabular-nums">{session.date}</span>
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-starlight">
                      {session.prefixName} {session.sessionNumber}
                      <span className="text-static"> · {session.cohortName}</span>
                    </span>
                    {!session.recorded && (
                      <span
                        className="shrink-0 font-mono text-[10px] text-static/60"
                        title="Recorded by another Ephymeris machine — run a rescan in Analytics to index it here"
                      >
                        not indexed
                      </span>
                    )}
                  </Row>
                ))
              ))}
          </motion.div>
        </AnimatePresence>
      </div>
    </TelemetryPanel>
  );
}

function Row({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="-mx-1.5 flex items-center gap-2 rounded-sm border-y border-transparent px-1.5 py-1.5 text-left transition-colors hover:border-pulsar/30 hover:bg-pulsar/[0.06]"
    >
      {children}
    </button>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-2 text-[12px] text-static">{children}</p>;
}

/**
 * Per-cohort reward accuracy across sessions, for the sparklines. One point
 * per session in date order: rewarded over administered trials pooled across
 * that session's runs — **the earned-drop rate, not choice accuracy**
 * (`DATA.md#rewarded-and-response-accuracy`). Rides the app-level analytics
 * cache, so it never disagrees with the rig's star temperatures about
 * freshness.
 */
function useCohortRewardSeries(): Array<{ id: string; name: string; values: number[] }> {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();
  const cohorts = useActiveCohorts();

  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => store.subscribe("data", bump), [store]);

  useEffect(() => {
    if (status !== "connected") return;
    for (const cohort of cohorts) {
      void store.load(client, cohort.id).catch(() => {
        // An unreadable archive keeps its sparkline empty; Analytics reports it.
      });
    }
  }, [client, status, store, cohorts, tick]);

  return useMemo(
    () =>
      cohorts.map((cohort) => {
        const summary = store.getSummary(cohort.id);
        if (!summary) return { id: cohort.id, name: cohort.name, values: [] };
        const bySession = new Map<string, { rewarded: number; administered: number }>();
        for (const run of summary.runs) {
          const outcomes = run.outcomes;
          if (!outcomes || outcomes.administered <= 0) continue;
          const acc = bySession.get(run.sessionId) ?? { rewarded: 0, administered: 0 };
          acc.rewarded += outcomes.rewarded;
          acc.administered += outcomes.administered;
          bySession.set(run.sessionId, acc);
        }
        // `summary.sessions` is date-ordered oldest-first.
        const values: number[] = [];
        for (const session of summary.sessions) {
          const acc = bySession.get(session.id);
          if (acc && acc.administered > 0) values.push(acc.rewarded / acc.administered);
        }
        return { id: cohort.id, name: cohort.name, values };
      }),
    // `tick` stands in for the summaries' contents behind stable references.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cohorts, store, tick],
  );
}

/** The most recent session folders across the archive; a session starting or
 *  ending refetches, so today's run appears without a reload. */
function useRecentSessions(): { sessions: DiskSession[]; loaded: boolean } {
  const { client, status } = useSidecar();
  const running = useRunningSession();
  const runningId = running?.session.id ?? null;
  const [state, setState] = useState<{ sessions: DiskSession[]; loaded: boolean }>({
    sessions: [],
    loaded: false,
  });

  useEffect(() => {
    if (status !== "connected") return;
    let cancelled = false;
    fetchRecentSessions(client, MAX_ROWS)
      .then((sessions) => {
        if (!cancelled) setState({ sessions, loaded: true });
      })
      .catch(() => {
        if (!cancelled) setState({ sessions: [], loaded: true });
      });
    return () => {
      cancelled = true;
    };
  }, [client, status, runningId]);

  return state;
}

const SPARK_W = 96;
const SPARK_H = 22;
const SPARK_PAD = 3;
/** Domain floor, below chance rather than at zero — no real reward rate
 *  lives near zero, and a fixed domain keeps cohorts comparable. */
const SPARK_MIN = 0.2;

/** One cohort's reward-accuracy line; the dashed guide is chance (0.5). */
function Sparkline({ values, title }: { values: number[]; title: string }) {
  const x = (i: number) =>
    values.length === 1 ? SPARK_W / 2 : SPARK_PAD + (i * (SPARK_W - 2 * SPARK_PAD)) / (values.length - 1);
  const y = (v: number) => {
    const t = Math.max(0, (v - SPARK_MIN) / (1 - SPARK_MIN));
    return SPARK_H - SPARK_PAD - t * (SPARK_H - 2 * SPARK_PAD);
  };
  const last = values[values.length - 1] ?? 0;
  return (
    <svg width={SPARK_W} height={SPARK_H} className="shrink-0" role="img" aria-label={title}>
      <title>{title}</title>
      <line
        x1={SPARK_PAD}
        y1={y(0.5)}
        x2={SPARK_W - SPARK_PAD}
        y2={y(0.5)}
        stroke="var(--color-halo)"
        strokeWidth="1"
        strokeDasharray="2 3"
      />
      <polyline
        points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
        fill="none"
        stroke="var(--color-pulsar)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(values.length - 1)} cy={y(last)} r="2" fill="var(--color-pulsar)" />
    </svg>
  );
}
