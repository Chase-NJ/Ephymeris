import { motion } from "framer-motion";
import { ArrowLeft, CircleAlert, Play, RotateCcw, Square, Undo2, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { PanelTitle } from "@/components/charts/PanelTitle";
import { NODE_FILL, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { Button, Select } from "@/components/common/controls";
import {
  useAllPortStatuses,
  useBoxOutputs,
  useFlashedSketches,
  useHardwareStore,
  useUtilityStatus,
} from "@/lib/hardware/context";
import { baselineColor, baselineLabel } from "@/lib/hardware/utility";
import { CASCADE, RISE, springSnappy } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { useSessionStore } from "@/lib/sessions/context";
import { defaultConfig, sketchName, type TaskProfile } from "@/lib/sessions/types";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

import { DEFAULT_STATUS_MATCH } from "../Scrollback";
import { parseLatestStatus } from "../UtilityControls";
import { BroadcastControls } from "./BroadcastControls";
import { FlashAllDialog } from "./FlashAllDialog";
import { MergedConsole } from "./MergedConsole";

/** The panel's share of the view's height; the asterism takes the rest. */
export const ALL_PANEL_HEIGHT = "54%";

const PORT_WORD: Record<string, string> = {
  IDLE: "idle",
  PASSTHROUGH: "console",
  FLASHING: "flashing",
  RESETTING: "resetting",
  IN_SESSION: "in session",
  ERROR: "error",
};

interface Report {
  label: string;
  ok: number;
  failures: Array<{ box: number; message: string }>;
}

/**
 * Debug Mode for the whole rig at once (`USER-GUIDE.md#commanding-every-box`).
 *
 * Everything a box's own panel can do — open and close its console, reset,
 * acknowledge an error, the utility sketch's switches and pulses and Prime,
 * flash, return to baseline, start and end a task, type into the console —
 * sent to every TARGETED box. Targets are the boxes the operator has chosen:
 * the chips here, or the stars themselves, ringed when they are in.
 *
 * NO NEW WIRE COMMAND. Each action is the per-box command, once per box, in
 * parallel where the sidecar allows it (every port has its own owner) and one
 * at a time where the app's convention says so (flashing). A command reaches a
 * box only in the state that box's own panel would allow it, and the report
 * under the buttons names any box that refused.
 */
export function AllBoxesPanel({
  bound,
  health,
  targets,
  hovered,
  onToggle,
  onTargets,
  onHover,
  onBack,
}: {
  bound: readonly number[];
  health: Partial<Record<number, BoxHealth>>;
  targets: ReadonlySet<number>;
  hovered: number | null;
  onToggle: (box: number) => void;
  onTargets: (boxes: number[]) => void;
  onHover: (box: number | null) => void;
  onBack: () => void;
}) {
  const { client } = useSidecar();
  const { settings } = useSettings();
  const store = useHardwareStore();
  const sessionStore = useSessionStore();
  const ports = useAllPortStatuses();
  const utility = useUtilityStatus();
  const flashed = useFlashedSketches(bound);
  const targetList = useMemo(() => bound.filter((b) => targets.has(b)), [bound, targets]);
  const outputs = useBoxOutputs(targetList);
  const labels = useMemo(() => new Map(settings.boxes.map((b) => [b.box, b.label])), [settings.boxes]);

  const [baud, setBaud] = useState<number>(settings.defaultBaud);
  const [busy, setBusy] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [flashOpen, setFlashOpen] = useState(false);
  const [utilityProfile, setUtilityProfile] = useState<TaskProfile | null>(null);
  const [taskProfile, setTaskProfile] = useState<TaskProfile | null>(null);

  const stateOf = (box: number) => ports[box]?.state ?? "IDLE";
  const detected = (box: number) => (health[box] ?? "absent") !== "absent";

  /** What a box is carrying — the baseline's word first, then the sidecar's
   *  record of its last flash, as in `NodeDetail`. */
  const sketchOf = (box: number): string | null => {
    const state = utility.boxes.find((b) => b.box === box)?.state;
    if (utility.configured && utility.sketchPath && state === "ready") return utility.sketchPath;
    return flashed.get(box)?.path ?? null;
  };

  // The one utility profile the rig generated — every box's controls mean the same.
  useEffect(() => {
    if (!utility.sketchPath) {
      setUtilityProfile(null);
      return;
    }
    let cancelled = false;
    getTaskProfile(client, utility.sketchPath)
      .then((p) => !cancelled && setUtilityProfile(p))
      .catch(() => !cancelled && setUtilityProfile(null));
    return () => {
      cancelled = true;
    };
  }, [client, utility.sketchPath]);

  const open = targetList.filter((b) => stateOf(b) === "PASSTHROUGH");
  const onUtility = open.filter((b) => sketchOf(b) === utility.sketchPath);

  // A task every open target carries — the only case "Start" can mean one thing.
  const sharedTask = useMemo(() => {
    const paths = new Set(open.map(sketchOf));
    if (paths.size !== 1) return null;
    const [path] = [...paths];
    return path && path !== utility.sketchPath ? path : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open.join(","), utility.sketchPath, flashed]);
  useEffect(() => {
    if (!sharedTask) {
      setTaskProfile(null);
      return;
    }
    let cancelled = false;
    getTaskProfile(client, sharedTask)
      .then((p) => !cancelled && setTaskProfile(p))
      .catch(() => !cancelled && setTaskProfile(null));
    return () => {
      cancelled = true;
    };
  }, [client, sharedTask]);

  const statuses = useMemo(
    () =>
      new Map(
        targetList.map((b) => [b, parseLatestStatus(outputs.get(b) ?? [], utilityProfile?.telemetry ?? null)]),
      ),
    [targetList, outputs, utilityProfile],
  );

  // Consoles this view opened close with it — a port left in PASSTHROUGH by a
  // panel nobody can see is claimed by no one (`NodeDetail`'s rule).
  const openedHere = useRef(new Set<number>());
  const portsRef = useRef(ports);
  portsRef.current = ports;
  useEffect(
    () => () => {
      for (const box of openedHere.current) {
        if (portsRef.current[box]?.state === "PASSTHROUGH") {
          void client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }).catch(() => {});
        }
      }
    },
    [client],
  );

  async function fanOut(label: string, boxes: number[], act: (box: number) => Promise<unknown>) {
    if (boxes.length === 0) return;
    setBusy(label);
    const results = await Promise.allSettled(boxes.map(act));
    const failures = results.flatMap((r, i) =>
      r.status === "rejected"
        ? [{ box: boxes[i] as number, message: r.reason instanceof Error ? r.reason.message : String(r.reason) }]
        : [],
    );
    setReport({ label, ok: boxes.length - failures.length, failures });
    setBusy(null);
  }

  const toOpen = targetList.filter((b) => stateOf(b) === "IDLE" && detected(b));
  const toReset = targetList.filter((b) => detected(b) && (stateOf(b) === "IDLE" || stateOf(b) === "PASSTHROUGH"));
  const inError = targetList.filter((b) => stateOf(b) === "ERROR");
  const offBaseline = targetList.filter((b) => {
    const state = utility.boxes.find((u) => u.box === b)?.state;
    return state === "pinned" || (sketchOf(b) !== null && sketchOf(b) !== utility.sketchPath);
  });

  const broadcast = (command: string) => {
    for (const box of onUtility) {
      void client.call(CMD.PORT_SEND, { box, text: command, lineEnding: "lf" });
    }
  };

  return (
    // Docked along the bottom, rising into place as the camera pulls back: the
    // asterism is wide, so it keeps the whole width of sky above the panel.
    <motion.aside
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 40 }}
      transition={{ type: "spring", stiffness: 320, damping: 34, mass: 0.9 }}
      className="telemetry pointer-events-auto absolute right-4 bottom-4 left-4 z-20 flex flex-col"
      style={{ height: ALL_PANEL_HEIGHT }}
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-halo/70 px-4 py-2.5">
        <Button variant="ghost" onClick={onBack} title="Back to the Dashboard (Esc)">
          <ArrowLeft size={13} strokeWidth={1.75} />
          Constellation
        </Button>
        <span className="min-w-0 flex-1">
          <PanelTitle
            name="All boxes"
            note={`${targetList.length} of ${bound.length} targeted · ${open.length} console${open.length === 1 ? "" : "s"} open`}
          />
        </span>
      </header>

      <motion.div
        variants={CASCADE}
        initial="hidden"
        animate="shown"
        className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1fr)] divide-x divide-halo/50"
      >
        <Column>
        <Section title="Targets" right={
          <span className="flex gap-2 font-mono text-[10px]">
            <Quick onClick={() => onTargets([...bound])}>all</Quick>
            <Quick onClick={() => onTargets(bound.filter(detected))}>detected</Quick>
            <Quick onClick={() => onTargets([])}>none</Quick>
          </span>
        }>
          <p className="mb-1.5 text-[11px] text-static">
            Click a box here or its star in the sky to take it in or out. Ringed stars are targeted.
          </p>
          <div className="grid grid-cols-2 gap-1.5" onPointerLeave={() => onHover(null)}>
            {bound.map((box) => {
              const on = targets.has(box);
              const state = health[box] ?? "absent";
              const baseline = utility.boxes.find((b) => b.box === box)?.state ?? null;
              return (
                <motion.button
                  key={box}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggle(box)}
                  onPointerEnter={() => onHover(box)}
                  whileTap={{ scale: 0.97 }}
                  transition={springSnappy}
                  className={`flex flex-col items-start rounded-sm border px-2 py-1.5 text-left transition-colors ${
                    on ? "border-pulsar/60 bg-pulsar/10" : "border-halo/70 opacity-60 hover:opacity-100"
                  } ${hovered === box ? "ring-1 ring-pulsar/50" : ""}`}
                >
                  <span className="flex w-full items-center gap-1.5">
                    <span className="size-[7px] rounded-full" style={{ background: NODE_FILL[state] }} />
                    <span className="font-mono text-[11px] text-starlight">Box {box}</span>
                    <span className="ml-auto font-mono text-[9.5px] text-static">
                      {state === "absent" ? "not detected" : (PORT_WORD[stateOf(box)] ?? stateOf(box))}
                    </span>
                  </span>
                  <span className="w-full truncate text-[11px] text-static">{labels.get(box) || `Box ${box}`}</span>
                  <span
                    className="font-mono text-[9.5px]"
                    style={{ color: baseline ? baselineColor(baseline) : "var(--color-static)" }}
                  >
                    {baseline ? baselineLabel(baseline) : "—"}
                  </span>
                </motion.button>
              );
            })}
          </div>
        </Section>

        <Section title="Connection">
          <div className="flex flex-wrap items-center gap-1.5">
            <Select
              label="Baud rate"
              value={baud}
              options={BAUD_RATES.map((rate) => ({ value: rate, label: `${rate}` }))}
              onChange={setBaud}
            />
            <Button
              variant="outline"
              disabled={busy !== null || toOpen.length === 0}
              onClick={() =>
                void fanOut("Open consoles", toOpen, async (box) => {
                  store.clearLines(box);
                  openedHere.current.add(box);
                  await client.call(CMD.PORT_PASSTHROUGH_OPEN, { box, baud });
                })
              }
            >
              Open {toOpen.length} console{toOpen.length === 1 ? "" : "s"}
            </Button>
            <Button
              variant="ghost"
              disabled={busy !== null || open.length === 0}
              onClick={() => void fanOut("Close consoles", open, (box) => client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }))}
            >
              Close {open.length}
            </Button>
            <Button
              variant="ghost"
              disabled={busy !== null || toReset.length === 0}
              onClick={() => void fanOut("Reset", toReset, (box) => client.call(CMD.PORT_RESET, { box }))}
            >
              <RotateCcw size={12} strokeWidth={1.75} />
              Reset {toReset.length}
            </Button>
            {inError.length > 0 && (
              <Button
                variant="outline"
                disabled={busy !== null}
                onClick={() => void fanOut("Acknowledge", inError, (box) => client.call(CMD.PORT_ERROR_ACK, { box }))}
              >
                <CircleAlert size={12} strokeWidth={1.75} />
                Acknowledge {inError.length} error{inError.length === 1 ? "" : "s"}
              </Button>
            )}
          </div>
          <Outcome busy={busy} report={report} />
        </Section>
        <Section title="Sketch">
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="outline" disabled={busy !== null || targetList.length === 0} onClick={() => setFlashOpen(true)}>
              <Zap size={12} strokeWidth={1.75} />
              Flash {targetList.length}…
            </Button>
            <Button
              variant="ghost"
              disabled={busy !== null || offBaseline.length === 0}
              title="Release every targeted box back to the utility sketch"
              onClick={() =>
                void fanOut("Return to baseline", offBaseline, async (box) => {
                  // Asking is what unpins; the close's IDLE then restores.
                  await client.call(CMD.UTILITY_ENSURE, { boxes: [box] });
                  if (stateOf(box) === "PASSTHROUGH") await client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box });
                })
              }
            >
              <Undo2 size={12} strokeWidth={1.75} />
              Return {offBaseline.length} to baseline
            </Button>
            {sharedTask && (
              <>
                <Button
                  variant="primary"
                  disabled={busy !== null}
                  title={`Send START to ${open.length} box${open.length === 1 ? "" : "es"} running ${sketchName(sharedTask)}`}
                  onClick={() =>
                    void fanOut("Start", open, (box) => {
                      sessionStore.resetBox(box);
                      const config = defaultConfig(taskProfile, settings.taskDefaults[sketchName(sharedTask)] ?? {});
                      return client.call(CMD.PORT_SEND_START, { box, sketchPath: sharedTask, config });
                    })
                  }
                >
                  <Play size={12} strokeWidth={2} />
                  Start {sketchName(sharedTask)}
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy !== null}
                  onClick={() =>
                    void fanOut("End", open, (box) =>
                      client.call(CMD.PORT_SEND, { box, text: "STOP", lineEnding: "lf" }),
                    )
                  }
                >
                  <Square size={11} strokeWidth={2} />
                  End
                </Button>
              </>
            )}
          </div>
          <SketchSummary boxes={targetList} sketchOf={sketchOf} />
        </Section>
        </Column>
        <Column>
        <Section
          title="Controls"
          right={
            <span className="font-mono text-[10px] text-static">
              reaching {onUtility.length} box{onUtility.length === 1 ? "" : "es"}
            </span>
          }
        >
          {!utilityProfile ? (
            <p className="text-[11px] text-static">The rig has no utility sketch, so there are no switches to show.</p>
          ) : onUtility.length === 0 ? (
            <p className="text-[11px] text-static">
              Open the consoles of boxes on the utility sketch — every switch, pulse and Prime here then
              reaches all of them at once.
            </p>
          ) : (
            <BroadcastControls profile={utilityProfile} boxes={onUtility} statuses={statuses} onSend={broadcast} />
          )}
          {utilityProfile?.telemetry && onUtility.length > 0 && (
            <TelemetryTable
              boxes={onUtility}
              fields={utilityProfile.telemetry.fields}
              statuses={statuses}
              hovered={hovered}
              onHover={onHover}
            />
          )}
        </Section>
        </Column>
        <Column>
        <Section title="Console" grow>
          <MergedConsole
            outputs={outputs}
            boxes={targetList}
            canSend={open.length > 0}
            statusMatch={utilityProfile?.telemetry?.match ?? DEFAULT_STATUS_MATCH}
            onSend={async (text, lineEnding) => {
              await fanOut("Send", open, (box) => client.call(CMD.PORT_SEND, { box, text, lineEnding }));
            }}
          />
        </Section>
        </Column>



      </motion.div>

      <FlashAllDialog open={flashOpen} boxes={targetList} baud={baud} onClose={() => setFlashOpen(false)} />
    </motion.aside>
  );
}

/** One of the panel's three columns, each scrolling on its own. */
function Column({ children }: { children: ReactNode }) {
  return (
    <div className="scrollbar-slim flex min-h-0 flex-col gap-4 overflow-y-auto px-4 py-3">{children}</div>
  );
}

function Section({
  title,
  right,
  grow = false,
  children,
}: {
  title: string;
  right?: ReactNode;
  grow?: boolean;
  children: ReactNode;
}) {
  return (
    <motion.section variants={RISE} className={`flex flex-col gap-1.5 ${grow ? "min-h-0 flex-1" : ""}`}>
      <div className="flex items-center gap-3">
        <h3 className="telemetry-section min-w-0 flex-1">{title}</h3>
        {right}
      </div>
      {children}
    </motion.section>
  );
}

function Quick({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="text-static transition-colors hover:text-starlight">
      {children}
    </button>
  );
}

/** The last fan-out, in words — and every box that refused, by name. */
function Outcome({ busy, report }: { busy: string | null; report: Report | null }) {
  if (busy) return <p className="font-mono text-[10px] text-static">{busy.toLowerCase()}…</p>;
  if (!report) return null;
  return (
    <div className="font-mono text-[10px]">
      <span className={report.failures.length ? "text-status-warning" : "text-static"}>
        {report.label}: {report.ok} ok
        {report.failures.length > 0 && ` · ${report.failures.length} refused`}
      </span>
      {report.failures.map((f) => (
        <p key={f.box} className="text-status-error">
          Box {f.box} — {f.message}
        </p>
      ))}
    </div>
  );
}

/** Each box's latest STATUS fields — the beams, the test, the pulse width. */
function TelemetryTable({
  boxes,
  fields,
  statuses,
  hovered,
  onHover,
}: {
  boxes: readonly number[];
  fields: ReadonlyArray<{ key: string; label: string }>;
  statuses: ReadonlyMap<number, Record<string, string> | null>;
  hovered: number | null;
  onHover: (box: number | null) => void;
}) {
  return (
    <div className="scrollbar-slim mt-2 overflow-x-auto">
      <table className="w-full border-collapse font-mono text-[10px]">
        <thead>
          <tr className="text-left text-static/60">
            <th className="py-0.5 pr-3 font-normal">box</th>
            {fields.map((f) => (
              <th key={f.key} className="py-0.5 pr-3 font-normal whitespace-nowrap">
                {f.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody onPointerLeave={() => onHover(null)}>
          {boxes.map((box) => (
            <tr
              key={box}
              onPointerEnter={() => onHover(box)}
              className={`border-t border-halo/40 ${hovered === box ? "bg-pulsar/[0.07]" : ""}`}
            >
              <td className="py-0.5 pr-3 text-pulsar/90">{box}</td>
              {fields.map((f) => (
                <td key={f.key} className="py-0.5 pr-3 text-starlight/85 tabular-nums">
                  {statuses.get(box)?.[f.key] ?? <span className="text-static/40">—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the targets carry, grouped: "4 on BOX_Utility · 2 on GRGL". */
function SketchSummary({ boxes, sketchOf }: { boxes: readonly number[]; sketchOf: (box: number) => string | null }) {
  const groups = new Map<string, number[]>();
  for (const box of boxes) {
    const path = sketchOf(box);
    const name = path ? sketchName(path) : "unknown";
    groups.set(name, [...(groups.get(name) ?? []), box]);
  }
  if (groups.size === 0) return null;
  return (
    <p className="font-mono text-[10px] text-static">
      {[...groups].map(([name, list], i) => (
        <span key={name}>
          {i > 0 && " · "}
          <span className="text-starlight/85">{list.length}</span> on {name}
          <span className="text-static/60"> ({list.join(", ")})</span>
        </span>
      ))}
    </p>
  );
}
