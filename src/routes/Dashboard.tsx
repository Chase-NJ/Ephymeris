import { motion } from "framer-motion";
import { ArrowRight, ChartLine, Rocket, Terminal, Users } from "lucide-react";
import { useNavigate } from "react-router";
import type { LucideIcon } from "lucide-react";

import { NODE_FILL, useBoxHealth, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { springPanel, springSnappy } from "@/lib/motion";
import { useActiveCohorts, useCohortsLoaded } from "@/lib/cohorts/context";
import { useRunningSession } from "@/lib/sessions/context";
import { useSettings } from "@/lib/settings/context";

/**
 * Dashboard / landing view (ephymeris_v1.0.md §3.3).
 *
 * Hero CTA over a three-tile row, then the two at-a-glance panels — cohorts
 * and rig health. Both read state the app-level providers already hold
 * (cohort summaries, presence poll, port states), so the landing page costs
 * no extra round-trips and never shows a spinner. Settings is intentionally
 * not a tile — it lives in one fixed, always-reachable place in the sidebar
 * rather than as browsable content (§3.2).
 */
export function Dashboard() {
  const navigate = useNavigate();
  const { settings } = useSettings();
  const cohorts = useActiveCohorts();
  const cohortsLoaded = useCohortsLoaded();
  const health = useBoxHealth();
  const running = useRunningSession();

  const cohortCount = cohorts.length;
  const boundBindings = settings.boxes.filter((b) => b.hardwareId !== null);
  const boundBoxes = boundBindings.map((b) => b.box);

  // §4.1: starting a session requires an existing cohort — now a live check
  // against the real cohort count rather than a hardcoded always-zero.
  //
  // Deliberately still only an *existence* check. "Ready to run" is now defined
  // (`starting-a-session.md` §1) but is a per-cohort property, and the CTA
  // routes through Launch, whose Step 1 is where a cohort gets picked — so
  // that's where the readiness check belongs and where it lives.
  const hasCohorts = cohortCount > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-4xl px-10 py-9"
    >
      <h1 className="font-display text-[22px] text-starlight">Dashboard</h1>

      <motion.button
        type="button"
        whileHover={{ y: -2 }}
        whileTap={{ scale: 0.995 }}
        transition={springSnappy}
        onClick={() => navigate(hasCohorts || running ? "/launch" : "/cohorts")}
        className="mt-6 flex w-full items-center justify-between rounded-lg bg-pulsar px-6 py-5 text-left"
      >
        <span className="flex items-center gap-4">
          {/* The Launch tab's own icon — the hero and the tab are the same door. */}
          <Rocket size={22} strokeWidth={1.75} className="shrink-0 text-void" />
          <span>
            <span className="block font-display text-lg font-semibold text-void">
              {running
                ? "Resume Session"
                : hasCohorts
                  ? "Start a Session"
                  : "Create a cohort to get started"}
            </span>
            <span className="mt-0.5 block text-[12px] text-void/70">
              {running
                ? "A session is running — open Launch to get back to it"
                : hasCohorts
                  ? "Configure boxes and begin data collection"
                  : "Sessions run against a cohort — you'll need one first"}
            </span>
          </span>
        </span>
        <ArrowRight size={20} strokeWidth={2} className="shrink-0 text-void" />
      </motion.button>

      <div className="mt-5 grid grid-cols-3 gap-3">
        <Tile
          icon={Users}
          label="Cohorts"
          status={`${cohortCount} active`}
          onClick={() => navigate("/cohorts")}
        />
        <Tile
          icon={ChartLine}
          label="Analytics"
          status="view"
          onClick={() => navigate("/analytics")}
        />
        <Tile
          icon={Terminal}
          label="Debug Mode"
          status={
            boundBoxes.length === 0
              ? "no boxes"
              : `${boundBoxes.length} ${boundBoxes.length === 1 ? "box" : "boxes"}`
          }
          onClick={() => navigate("/debug")}
        />
      </div>

      <div className="mt-5 grid grid-cols-1 items-start gap-3 md:grid-cols-2">
        <Panel
          title="Cohorts"
          empty={
            cohortsLoaded && cohortCount === 0
              ? "No cohorts yet — create one to start recording sessions."
              : null
          }
        >
          {cohorts.slice(0, MAX_ROWS).map((cohort) => (
            <PanelRow key={cohort.id} onClick={() => navigate(`/cohorts/${cohort.id}`)}>
              <span className="min-w-0 flex-1 truncate text-[13px] text-starlight">
                {cohort.name}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-static">
                {cohort.animalCount} animal{cohort.animalCount === 1 ? "" : "s"} ·{" "}
                {cohort.groupCount} group{cohort.groupCount === 1 ? "" : "s"}
              </span>
            </PanelRow>
          ))}
          {cohortCount > MAX_ROWS && (
            <PanelFooterLink onClick={() => navigate("/cohorts")}>
              all {cohortCount} cohorts
            </PanelFooterLink>
          )}
        </Panel>

        <Panel
          title="Rig"
          empty={
            boundBindings.length === 0
              ? "No boxes bound yet — box setup in Config binds each one to a board."
              : null
          }
        >
          {boundBindings.map((binding) => {
            const state = health[binding.box] ?? "absent";
            return (
              <PanelRow key={binding.box} onClick={() => navigate("/debug")}>
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
              </PanelRow>
            );
          })}
        </Panel>
      </div>
    </motion.div>
  );
}

/** Rows before a cohort panel defers to the full grid. */
const MAX_ROWS = 5;

/** The sidebar constellation's health states, in words for the row readout. */
const HEALTH_LABEL: Record<BoxHealth, string> = {
  nominal: "active",
  idle: "connected",
  absent: "not detected",
  fault: "error",
};

function Panel({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string | null;
  children: React.ReactNode;
}) {
  return (
    <section className="surface rounded-md p-4">
      <h2 className="text-[13px] font-medium text-starlight">{title}</h2>
      {empty ? (
        <p className="mt-2 text-[12px] leading-relaxed text-static">{empty}</p>
      ) : (
        <div className="mt-2 flex flex-col">{children}</div>
      )}
    </section>
  );
}

function PanelRow({
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
      className="-mx-1.5 flex items-center gap-2 rounded-sm px-1.5 py-1.5 text-left transition-colors hover:bg-nebula"
    >
      {children}
    </button>
  );
}

function PanelFooterLink({
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

function Tile({
  icon: Icon,
  label,
  status,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  status: string;
  onClick: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={springSnappy}
      className="surface group flex flex-col items-start gap-3 rounded-md p-4 text-left"
    >
      <Icon size={18} strokeWidth={1.75} className="text-pulsar" />
      <span>
        <span className="block text-[13px] font-medium text-starlight">{label}</span>
        <span className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-static">
          {status}
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </span>
    </motion.button>
  );
}
