import { motion } from "framer-motion";
import { ArrowRight, Radio, Rocket, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { BoxRoster } from "@/components/dashboard/BoxRoster";
import { EntranceTile, RigMotif, TaskMotif } from "@/components/dashboard/EntranceTile";
import { Observatory } from "@/components/dashboard/Observatory";
import { RecordingTile } from "@/components/dashboard/RecordingTile";
import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { SessionDock } from "@/components/sessions/SessionDock";
import { setRigSelection } from "@/lib/constellations/viewMemory";
import { useActiveCohorts } from "@/lib/cohorts/context";
import { CASCADE, PANEL_TRAVEL, RISE, springPanel, springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useRunningSession } from "@/lib/sessions/context";
import { sessionDoor } from "@/lib/sessions/flow";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Dashboard / landing view (`USER-GUIDE.md#a-tour-of-the-app`).
 *
 * The rig's constellation is the page — the same 3D sky Debug flies, same
 * shared camera and selection (`viewMemory.ts`), so moving between the two
 * reads as one continuous sky. Over it, a telemetry display
 * (`ARCHITECTURE.md#telemetry-panels`) in two columns: **command** on the left
 * (the hero, the recording door, sessions in flight, then the doors to the
 * rig's wiring and its tasks) and **readouts** on the right (the box roster
 * and the observatory).
 *
 * THE ROSTER AND THE SKY ARE ONE INSTRUMENT. Hovering a box row lights its
 * star; hovering a star lights its row; clicking either opens the box's
 * console in Debug, the camera flying there as the roster hands its place to
 * the panel. The roster's foot is the door to commanding every box at once
 * (`/debug/all`), drawn as the rig's own asterism.
 *
 * Data stays cheap: providers the app already holds, the app-level analytics
 * cache, and `analytics.recentSessions` (folder names only). No spinners.
 */
export function Dashboard() {
  const navigate = useNavigate();
  const { settings } = useSettings();
  const { status } = useSidecar();
  const cohorts = useActiveCohorts();
  const health = useBoxHealth();
  const running = useRunningSession();
  const [hovered, setHovered] = useState<number | null>(null);
  /** The roster is handing its place to a Debug panel — it leaves rightward. */
  const [handoff, setHandoff] = useState(false);

  const hasCohorts = cohorts.length > 0;
  const bound = settings.boxes.filter((b) => b.hardwareId !== null);
  const connected = bound.filter((b) => (health[b.box] ?? "absent") !== "absent").length;
  const anyFault = bound.some((b) => health[b.box] === "fault");

  /*
   * **The Dashboard never renders a focused sky.** The rig selection is
   * module-level and survives navigation (`viewMemory.ts`), so leaving Debug by
   * any route other than its own Back used to arrive parked in a star's
   * close-up. Cleared on the incoming side, on mount — route transitions
   * overlap mounts, so an outgoing view's cleanup can run after this one acts.
   */
  useEffect(() => {
    setRigSelection(null);
  }, []);

  const openBox = (box: number) => {
    setHandoff(true);
    setRigSelection(box);
    navigate("/debug");
  };

  return (
    // No `overflow-hidden`: the shared canvas reaches left under the sidebar.
    <div className="relative h-full">
      {/* The sky — deliberately outside every entrance animation: the shared
          canvas lives in this element, and fading it would blink the
          constellation out and back between Dashboard and Debug. */}
      <div className="absolute inset-0">
        <DebugConstellation
          // Always null, never the store value — see the clearing effect.
          selected={null}
          docksPanel={false}
          highlight={hovered}
          onHover={setHovered}
          onSelect={(box) => {
            if (box !== null) openBox(box);
          }}
        />
      </div>

      <div className="pointer-events-none absolute inset-0">
        {/* Command. Opacity-only: Debug's title lands on the same title line,
            so the two crossfade as a word being swapped. */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-y-0 left-0 w-[392px] overflow-y-auto p-4 pl-8"
        >
          <header className="pt-3 pb-4">
            <div className="flex items-center gap-2 font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">
              <span>Telemetry · Rig</span>
              <span
                aria-hidden
                className={`size-1.5 rounded-full ${status === "connected" ? "bg-ion" : "bg-halo"}`}
              />
              <span>{status === "connected" ? "link" : "no link"}</span>
            </div>
            <h1 className="font-display text-[22px] text-starlight">Dashboard</h1>
            <p className="mt-0.5 font-mono text-[10px] text-static/70">
              <span
                style={{
                  color: anyFault
                    ? "var(--color-status-error)"
                    : bound.length > 0 && connected === bound.length
                      ? "var(--color-status-ok)"
                      : undefined,
                }}
              >
                {bound.length === 0 ? "no boxes bound" : `${connected}/${bound.length} boxes on the bus`}
              </span>
              {" · "}
              {cohorts.length} cohort{cohorts.length === 1 ? "" : "s"}
              {running && (
                <>
                  {" · "}
                  <span style={{ color: "var(--color-status-ok)" }}>session running</span>
                </>
              )}
            </p>
          </header>

          <motion.div
            variants={CASCADE}
            initial="hidden"
            animate="shown"
            className="pointer-events-auto flex flex-col gap-3"
          >
            <motion.div variants={RISE}>
              <LaunchButton
                running={running !== null}
                hasCohorts={hasCohorts}
                onClick={() => {
                  if (running) navigate(sessionDoor(running));
                  else navigate(hasCohorts ? "/session/new" : "/cohorts");
                }}
              />
            </motion.div>

            {running === null && (
              <motion.div variants={RISE}>
                <RecordingTile
                  disabled={!hasCohorts}
                  onOpen={() => navigate("/session/new?mode=recording")}
                  onSettings={() => navigate("/recording")}
                />
              </motion.div>
            )}

            <motion.div variants={RISE}>
              <SessionDock />
            </motion.div>

            {/* The two places that have no presence on this page — the rig's
                wiring and its tasks — as a paired row of doors. */}
            <motion.div variants={RISE} className="grid grid-cols-2 gap-3">
              <EntranceTile
                icon={Radio}
                label="Rig"
                caption="Which board is box 3?"
                status={
                  bound.length === 0 ? "nothing bound" : `${bound.length} box${bound.length === 1 ? "" : "es"} bound`
                }
                motif={<RigMotif />}
                onOpen={() => navigate("/config")}
              />
              <EntranceTile
                icon={Workflow}
                label="Task"
                caption="What the animal does — this rig's tasks"
                motif={<TaskMotif />}
                onOpen={() => navigate("/task")}
              />
            </motion.div>
          </motion.div>
        </motion.div>

        {/* Readouts. On a box click this column hands its place to Debug's
            docked panel, so it leaves toward the edge the panel arrives from,
            on the panel's spring. */}
        <motion.div
          initial={{ opacity: 0, x: PANEL_TRAVEL }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: handoff ? PANEL_TRAVEL : 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-y-0 right-0 w-[392px] overflow-y-auto p-4 pl-0"
        >
          <motion.div
            variants={CASCADE}
            initial="hidden"
            animate="shown"
            className="pointer-events-auto flex flex-col gap-3 pt-3"
          >
            <motion.div variants={RISE}>
              <BoxRoster
                health={health}
                hovered={hovered}
                onHover={setHovered}
                onOpen={openBox}
                onOpenAll={() => {
                  setHandoff(true);
                  navigate("/debug/all");
                }}
                onBind={() => navigate("/config")}
              />
            </motion.div>
            <motion.div variants={RISE}>
              <Observatory />
            </motion.div>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}

/**
 * The booster plume: exhaust particles thrown down-left, opposite the
 * Rocket glyph's 45° heading, from just behind its nozzle. Void-on-Pulsar
 * like the icon itself — the palette is matte, so the fire is drawn with
 * motion, not colour or glow (`ARCHITECTURE.md#theme`).
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
 * The hero CTA — still the page's single most prominent element, now
 * the head of the command column at the column's shared width. Hovering lifts
 * the rocket toward its heading and lights the booster trail; the trail loop
 * stands down under reduced motion. Deliberately opaque: the one solid tile,
 * because the primary action should not dissolve into the sky behind it.
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
      className="group flex w-full items-center gap-4 rounded-lg bg-pulsar py-4 pl-5 pr-6 text-left"
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
      <span className="min-w-0 flex-1">
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
        className="shrink-0 text-void transition-transform group-hover:translate-x-0.5"
      />
    </motion.button>
  );
}
