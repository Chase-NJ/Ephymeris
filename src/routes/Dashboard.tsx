import { motion } from "framer-motion";
import { Children, useEffect, useState } from "react";
import { ArrowRight, ChartLine, Rocket, Terminal, Users } from "lucide-react";
import { useNavigate } from "react-router";
import type { LucideIcon } from "lucide-react";

import { NODE_FILL, useBoxHealth, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { SessionDock } from "@/components/sessions/SessionDock";
import { listSessions } from "@/lib/analytics/commands";
import type { SessionListItem } from "@/lib/analytics/types";
import { springPanel, springSnappy } from "@/lib/motion";
import { useActiveCohorts, useCohortsLoaded } from "@/lib/cohorts/context";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useRunningSession } from "@/lib/sessions/context";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import type { SessionStatus } from "@/lib/ws/protocol";

/**
 * Dashboard / landing view (ephymeris_v1.0.md §3.3).
 *
 * A compact hero CTA — with the session dock beside it — over three summary
 * cards, each pairing a destination with its at-a-glance state: Cohorts lists
 * the active cohorts, Debug Mode lists the rig's boxes with live health, and
 * Analytics previews the most recent recorded session. The dock is the former
 * Launch page's content (`SessionDock`): the running session's status and way
 * back into Mission Control, plus unfinished and crash-orphaned set-ups —
 * the Dashboard is the hub for getting into a session now that the Launch
 * nav item is retired (§3.2). Everything reads state the app-level providers
 * already hold or a DB-only sidecar call (`sessions.list` never touches the
 * filesystem), so the landing page stays cheap and never shows a spinner.
 * Settings is intentionally not a card — it lives in one fixed,
 * always-reachable place in the sidebar rather than as browsable content
 * (§3.2).
 */
export function Dashboard() {
  const navigate = useNavigate();
  const { settings } = useSettings();
  const cohorts = useActiveCohorts();
  const cohortsLoaded = useCohortsLoaded();
  const health = useBoxHealth();
  const running = useRunningSession();
  const { latest, loaded: latestLoaded } = useLatestSession();

  const cohortCount = cohorts.length;
  const boundBindings = settings.boxes.filter((b) => b.hardwareId !== null);
  const connectedCount = boundBindings.filter(
    (b) => (health[b.box] ?? "absent") !== "absent",
  ).length;

  // §4.1: starting a session requires an existing cohort — now a live check
  // against the real cohort count rather than a hardcoded always-zero.
  //
  // Deliberately still only an *existence* check. "Ready to run" is now defined
  // (`starting-a-session.md` §1) but is a per-cohort property, and Step 1
  // (`/session/new`) is where a cohort gets picked — so that's where the
  // readiness check belongs and where it lives.
  const hasCohorts = cohortCount > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-5xl px-10 py-9"
    >
      <h1 className="font-display text-[22px] text-starlight">Dashboard</h1>

      <div className="mt-6 flex flex-wrap items-start gap-3">
        <LaunchButton
          running={running !== null}
          hasCohorts={hasCohorts}
          onClick={() => {
            // Straight to the destination — the Launch waypoint is retired
            // (§3.2): Mission Control while a session runs, Step 1 otherwise.
            if (running) {
              navigate(
                `/session/${running.session.id}/control?cohort=${running.session.cohortId}`,
              );
            } else {
              navigate(hasCohorts ? "/session/new" : "/cohorts");
            }
          }}
        />
        <SessionDock />
      </div>

      <div className="mt-5 grid grid-cols-1 items-start gap-3 md:grid-cols-2">
        <SummaryCard
          icon={Users}
          label="Cohorts"
          status={`${cohortCount} active`}
          onOpen={() => navigate("/cohorts")}
          empty={
            cohortsLoaded && cohortCount === 0
              ? "No cohorts yet — create one to start recording sessions."
              : null
          }
        >
          {cohorts.slice(0, MAX_ROWS).map((cohort) => (
            <CardRow key={cohort.id} onClick={() => navigate(`/cohorts/${cohort.id}`)}>
              <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                {cohort.name}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-static">
                {cohort.animalCount} animal{cohort.animalCount === 1 ? "" : "s"} ·{" "}
                {cohort.groupCount} group{cohort.groupCount === 1 ? "" : "s"}
              </span>
            </CardRow>
          ))}
          {cohortCount > MAX_ROWS && (
            <CardFooterLink onClick={() => navigate("/cohorts")}>
              all {cohortCount} cohorts
            </CardFooterLink>
          )}
        </SummaryCard>

        <SummaryCard
          icon={Terminal}
          label="Debug Mode"
          status={
            boundBindings.length === 0
              ? "no boxes"
              : `${connectedCount}/${boundBindings.length} connected`
          }
          onOpen={() => navigate("/debug")}
          empty={
            boundBindings.length === 0
              ? "No boxes bound yet — box setup in Config binds each one to a board."
              : null
          }
        >
          {boundBindings.map((binding) => {
            const state = health[binding.box] ?? "absent";
            return (
              <CardRow key={binding.box} onClick={() => navigate("/debug")}>
                <span
                  aria-hidden
                  className="size-[7px] shrink-0 rounded-full"
                  style={{ background: NODE_FILL[state] }}
                />
                <span className="shrink-0 font-mono text-[11px] text-static">
                  Box {binding.box}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                  {binding.label || `Box ${binding.box}`}
                </span>
                <span className="shrink-0 font-mono text-[11px] text-static">
                  {HEALTH_LABEL[state]}
                </span>
              </CardRow>
            );
          })}
        </SummaryCard>
      </div>

      <div className="mt-3">
        <SummaryCard
          icon={ChartLine}
          label="Analytics"
          status={latest ? "latest session" : latestLoaded ? "no sessions" : "view"}
          onOpen={() => navigate("/analytics")}
          empty={
            latestLoaded && !latest
              ? "No sessions recorded yet — the most recent one will preview here."
              : null
          }
        >
          {latest && (
            <CardRow onClick={() => navigate("/analytics")}>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] text-starlight">
                  {latest.session.prefixName} {latest.session.sessionNumber}
                  <span className="text-static"> · {latest.cohortName}</span>
                </span>
                <span className="mt-0.5 block font-mono text-[11px] text-static">
                  {latest.session.date}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-6">
                <Stat
                  label="runs"
                  value={latest.session.runCount != null ? String(latest.session.runCount) : "—"}
                />
                <Stat label="length" value={durationLabel(latest.session)} />
                <span className="flex flex-col items-end">
                  <span className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="size-[7px] rounded-full"
                      style={{ background: SESSION_STATUS[latest.session.status].color }}
                    />
                    <span className="font-mono text-[13px] text-starlight">
                      {SESSION_STATUS[latest.session.status].label}
                    </span>
                  </span>
                  <span className="font-mono text-[10px] uppercase tracking-wide text-static">
                    status
                  </span>
                </span>
              </span>
            </CardRow>
          )}
        </SummaryCard>
      </div>
    </motion.div>
  );
}

/** Rows before the cohort card defers to the full grid. */
const MAX_ROWS = 5;

/** The sidebar constellation's health states, in words for the row readout. */
const HEALTH_LABEL: Record<BoxHealth, string> = {
  nominal: "active",
  idle: "connected",
  absent: "not detected",
  fault: "error",
};

/**
 * Session status, in words and a dot colour. Semantic status colours mark
 * state only (§2.2); `completed` takes Pulsar because a finished session is a
 * result, not a condition needing attention.
 */
const SESSION_STATUS: Record<SessionStatus, { label: string; color: string }> = {
  running: { label: "running", color: "var(--color-status-ok)" },
  completed: { label: "completed", color: "var(--color-pulsar)" },
  configuring: { label: "unfinished", color: "var(--color-status-warning)" },
  aborted: { label: "aborted", color: "var(--color-status-error)" },
};

/** Wall-clock length of a session, from its run record. */
function durationLabel(session: SessionListItem): string {
  if (!session.endedAt) return session.status === "running" ? "in progress" : "—";
  const ms = Date.parse(session.endedAt) - Date.parse(session.startedAt);
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const mins = Math.round(ms / 60_000);
  const hours = Math.floor(mins / 60);
  return hours > 0 ? `${hours}h ${mins % 60}m` : `${mins}m`;
}

/** The sidecar's own ordering key for sessions: (date, startedAt). */
function isLater(a: SessionListItem, b: SessionListItem): boolean {
  if (a.date !== b.date) return a.date > b.date;
  return a.startedAt > b.startedAt;
}

interface LatestSession {
  session: SessionListItem;
  cohortName: string;
}

/**
 * The most recent session across all active cohorts, for the Analytics
 * preview. `sessions.list` is DB-only by construction (`analytics.md` §9), so
 * one call per cohort keeps the landing page's no-spinner rule intact. A
 * session starting or ending refetches, so the preview never shows a stale
 * "running".
 */
function useLatestSession(): { latest: LatestSession | null; loaded: boolean } {
  const { client, status } = useSidecar();
  const cohorts = useActiveCohorts();
  const cohortsLoaded = useCohortsLoaded();
  const running = useRunningSession();
  const runningId = running?.session.id ?? null;
  const [state, setState] = useState<{ latest: LatestSession | null; loaded: boolean }>({
    latest: null,
    loaded: false,
  });

  useEffect(() => {
    if (status !== "connected" || !cohortsLoaded) return;
    if (cohorts.length === 0) {
      setState({ latest: null, loaded: true });
      return;
    }
    let cancelled = false;
    void (async () => {
      const results = await Promise.allSettled(
        cohorts.map((cohort) => listSessions(client, cohort.id)),
      );
      if (cancelled) return;
      let best: LatestSession | null = null;
      results.forEach((result, i) => {
        if (result.status !== "fulfilled") return;
        // `sessions.list` orders oldest-first, so each cohort's candidate is
        // its last element.
        const last = result.value[result.value.length - 1];
        if (!last) return;
        if (!best || isLater(last, best.session)) {
          best = { session: last, cohortName: cohorts[i]!.name };
        }
      });
      setState({ latest: best, loaded: true });
    })();
    return () => {
      cancelled = true;
    };
  }, [client, status, cohortsLoaded, cohorts, runningId]);

  return state;
}

/**
 * The booster plume: exhaust particles thrown down-left, opposite the
 * Rocket glyph's 45° heading, from just behind its nozzle. Void-on-Pulsar
 * like the icon itself — the palette is matte, so the fire is drawn with
 * motion, not colour or glow (§2.2).
 */
const EXHAUST: ReadonlyArray<{
  x: number;
  y: number;
  size: number;
  throwPx: number;
  duration: number;
  delay: number;
}> = [
  { x: 4, y: 17, size: 4, throwPx: 10, duration: 0.6, delay: 0 },
  { x: 7, y: 19, size: 3, throwPx: 12, duration: 0.7, delay: 0.22 },
  { x: 2, y: 15, size: 2.5, throwPx: 9, duration: 0.55, delay: 0.42 },
];

/**
 * The hero CTA — the screen's single most prominent element (§3.3), but
 * self-sized now rather than a full-width slab, so the summary cards get the
 * room. Hovering lifts the rocket toward its heading and lights the booster
 * trail; the trail loop stands down under reduced motion.
 */
function LaunchButton({
  running,
  hasCohorts,
  onClick,
}: {
  running: boolean;
  hasCohorts: boolean;
  onClick: () => void;
}) {
  const reduceMotion = useReduceMotion();

  return (
    <motion.button
      type="button"
      initial="idle"
      animate="idle"
      whileHover="hover"
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="group flex items-center gap-4 rounded-lg bg-pulsar py-4 pl-5 pr-6 text-left"
    >
      <span className="relative shrink-0" aria-hidden>
        <motion.span
          variants={{ idle: { x: 0, y: 0 }, hover: { x: 2, y: -2 } }}
          transition={springSnappy}
          className="block"
        >
          <Rocket size={24} strokeWidth={1.75} className="text-void" />
        </motion.span>
        {!reduceMotion &&
          EXHAUST.map((p, i) => (
            <motion.span
              key={i}
              variants={{
                idle: { opacity: 0, x: 0, y: 0 },
                hover: {
                  opacity: [0, 0.7, 0],
                  x: [0, -p.throwPx],
                  y: [0, p.throwPx],
                  transition: {
                    duration: p.duration,
                    repeat: Infinity,
                    delay: p.delay,
                    ease: "easeOut",
                  },
                },
              }}
              className="absolute rounded-full bg-void"
              style={{ left: p.x, top: p.y, width: p.size, height: p.size }}
            />
          ))}
      </span>
      <span>
        <span className="block font-display text-base font-semibold text-void">
          {running
            ? "Resume Session"
            : hasCohorts
              ? "Start a Session"
              : "Create a cohort to get started"}
        </span>
        <span className="mt-0.5 block text-[12px] text-void/70">
          {running
            ? "A session is running — jump back into Mission Control"
            : hasCohorts
              ? "Configure boxes and begin data collection"
              : "Sessions run against a cohort — you'll need one first"}
        </span>
      </span>
      <ArrowRight
        size={18}
        strokeWidth={2}
        className="ml-3 shrink-0 text-void transition-transform group-hover:translate-x-0.5"
      />
    </motion.button>
  );
}

/**
 * One destination card: a clickable header (icon, label, live status, arrow —
 * the old tile) over that destination's at-a-glance rows (the old panel).
 * Header and rows navigate independently, so the merge loses no click target.
 */
function SummaryCard({
  icon: Icon,
  label,
  status,
  onOpen,
  empty,
  children,
}: {
  icon: LucideIcon;
  label: string;
  status: string;
  onOpen: () => void;
  empty: string | null;
  children?: React.ReactNode;
}) {
  return (
    <section className="surface overflow-hidden rounded-md">
      <button
        type="button"
        onClick={onOpen}
        className="group flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-halo/30"
      >
        <Icon size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
        <span className="text-[13px] font-medium text-starlight">{label}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1 font-mono text-[11px] text-static">
          {status}
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </button>
      {(empty || Children.toArray(children).length > 0) && (
        <div className="border-t border-halo px-4 pb-3 pt-2">
          {empty ? (
            <p className="py-1 text-[12px] leading-relaxed text-static">{empty}</p>
          ) : (
            <div className="flex flex-col">{children}</div>
          )}
        </div>
      )}
    </section>
  );
}

function CardRow({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="-mx-1.5 flex items-center gap-2 rounded-sm px-1.5 py-1.5 text-left transition-colors hover:bg-halo/50"
    >
      {children}
    </button>
  );
}

function CardFooterLink({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group mt-1 flex items-center gap-1 self-start font-mono text-[11px] text-static hover:text-starlight"
    >
      {children}
      <ArrowRight
        size={11}
        strokeWidth={2}
        className="transition-transform group-hover:translate-x-0.5"
      />
    </button>
  );
}

/** One right-aligned figure in the Analytics preview row. */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex shrink-0 flex-col items-end">
      <span className="font-mono text-[13px] text-starlight">{value}</span>
      <span className="font-mono text-[10px] uppercase tracking-wide text-static">{label}</span>
    </span>
  );
}
