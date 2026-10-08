import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { useMemo } from "react";

import { NODE_FILL, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { TelemetryPanel } from "@/components/common/TelemetryPanel";
import { useRigSky } from "@/components/constellation3d/useRigSky";
import { useAllPortStatuses, useUtilityStatus } from "@/lib/hardware/context";
import { baselineColor, baselineLabel } from "@/lib/hardware/utility";
import { springSnappy } from "@/lib/motion";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";

/** The port states, as the roster says them — short, and the operator's words. */
const PORT_WORD: Record<string, string> = {
  IDLE: "idle",
  PASSTHROUGH: "console",
  FLASHING: "flashing",
  RESETTING: "resetting",
  IN_SESSION: "in session",
  ERROR: "error",
};

const HEALTH_WORD: Record<BoxHealth, string> = {
  nominal: "active",
  idle: "connected",
  absent: "not detected",
  fault: "error",
};

/**
 * The rig's boxes as a live roster (`USER-GUIDE.md#a-tour-of-the-app`).
 *
 * ONE THING, TWO DRAWINGS. Each row is a star in the sky behind it: hovering
 * a row lights its star, hovering a star lights its row, and clicking either
 * opens that box's console in Debug. The roster adds what the sky cannot show
 * at a glance — the port's state and what the baseline is doing with it.
 *
 * At its foot, the door to commanding every box at once — drawn as this rig's
 * own asterism in miniature, because that is where it goes.
 */
export function BoxRoster({
  health,
  hovered,
  onHover,
  onOpen,
  onOpenAll,
  onBind,
}: {
  health: Partial<Record<number, BoxHealth>>;
  /** The box lit from the sky. */
  hovered: number | null;
  onHover: (box: number | null) => void;
  onOpen: (box: number) => void;
  onOpenAll: () => void;
  onBind: () => void;
}) {
  const { settings } = useSettings();
  const bound = useBoundBoxes();
  const ports = useAllPortStatuses();
  const utility = useUtilityStatus();
  const labels = useMemo(() => new Map(settings.boxes.map((b) => [b.box, b.label])), [settings.boxes]);

  const connected = bound.filter((box) => (health[box] ?? "absent") !== "absent").length;
  const anyFault = bound.some((box) => health[box] === "fault");

  return (
    <TelemetryPanel
      name="Boxes"
      note={
        bound.length === 0 ? (
          "none bound"
        ) : (
          <span
            style={{
              color: anyFault
                ? "var(--color-status-error)"
                : connected === bound.length
                  ? "var(--color-status-ok)"
                  : undefined,
            }}
          >
            {connected}/{bound.length} on the bus
          </span>
        )
      }
    >
      {bound.length === 0 ? (
        <div className="flex flex-col items-start gap-2 py-1">
          <p className="text-[12px] text-static">No boxes bound yet — the Rig tab binds each one to a board.</p>
          <button
            type="button"
            onClick={onBind}
            className="flex items-center gap-1 font-mono text-[11px] text-static transition-colors hover:text-starlight"
          >
            bind boxes on the Rig tab <ArrowRight size={11} strokeWidth={1.75} />
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-[14px_34px_minmax(0,1fr)_auto] gap-x-2 border-b border-halo/70 pb-1 font-mono text-[8.5px] tracking-[0.14em] text-static/60 uppercase">
            <span />
            <span>box</span>
            <span>label · port</span>
            <span className="text-right">baseline</span>
          </div>
          <ul className="flex flex-col py-0.5" onPointerLeave={() => onHover(null)}>
            {bound.map((box) => {
              const state = health[box] ?? "absent";
              const port = ports[box]?.state ?? "IDLE";
              const baseline = utility.boxes.find((b) => b.box === box)?.state ?? null;
              const lit = hovered === box;
              return (
                <li key={box}>
                  <button
                    type="button"
                    onClick={() => onOpen(box)}
                    onPointerEnter={() => onHover(box)}
                    onFocus={() => onHover(box)}
                    onBlur={() => onHover(null)}
                    className={`group grid w-full grid-cols-[14px_34px_minmax(0,1fr)_auto] items-center gap-x-2 rounded-sm border-y px-0 py-1.5 text-left transition-colors focus:outline-none ${
                      lit ? "border-pulsar/40 bg-pulsar/[0.07]" : "border-transparent hover:bg-halo/25"
                    }`}
                  >
                    <motion.span
                      aria-hidden
                      className="mx-auto size-[7px] rounded-full"
                      animate={{ scale: lit ? 1.5 : 1, backgroundColor: NODE_FILL[state] }}
                      transition={springSnappy}
                    />
                    <span className="font-mono text-[11px] text-static tabular-nums">Box {box}</span>
                    <span className="min-w-0 truncate text-[12.5px] text-starlight">
                      {labels.get(box) || `Box ${box}`}
                      <span className="ml-1.5 font-mono text-[10px] text-static/70">
                        {state === "absent" ? HEALTH_WORD.absent : (PORT_WORD[port] ?? port.toLowerCase())}
                      </span>
                    </span>
                    <span
                      className="shrink-0 text-right font-mono text-[10px]"
                      style={{ color: baseline ? baselineColor(baseline) : "var(--color-static)" }}
                    >
                      {baseline ? baselineLabel(baseline) : "—"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <AllBoxesDoor health={health} onOpen={onOpenAll} />
        </>
      )}
    </TelemetryPanel>
  );
}

/**
 * The door to Debug's all-boxes view: this rig's asterism in miniature, each
 * box's star in its health colour. Hovering draws the links in and brings the
 * stars up — the gesture previews the arrival, where every star is ringed.
 */
function AllBoxesDoor({
  health,
  onOpen,
}: {
  health: Partial<Record<number, BoxHealth>>;
  onOpen: () => void;
}) {
  const bound = useBoundBoxes();
  const key = bound.join(",");
  const occupants = useMemo(
    () => bound.map((box) => ({ occupantId: String(box), box })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );
  const sky = useRigSky(occupants);

  const W = 112;
  const H = 52;
  const PAD = 7;
  const drawn = useMemo(() => {
    const xs = sky.points.map((p) => p.position[0]);
    const ys = sky.points.map((p) => p.position[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const span = Math.max(maxX - minX, (maxY - minY) * ((W - 2 * PAD) / (H - 2 * PAD)), 1e-6);
    const scale = (W - 2 * PAD) / span;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    return sky.points.map((p) => ({
      x: W / 2 + (p.position[0] - cx) * scale,
      y: H / 2 - (p.position[1] - cy) * scale,
      box: p.box,
    }));
  }, [sky]);

  return (
    <motion.button
      type="button"
      onClick={onOpen}
      initial="rest"
      animate="rest"
      whileHover="hover"
      whileFocus="hover"
      whileTap={{ scale: 0.985 }}
      className="group mt-1.5 flex w-full items-center gap-3 rounded-sm border border-halo/80 bg-void/30 py-1.5 pr-3 pl-1.5 text-left transition-colors hover:border-pulsar/60 focus:outline-none focus-visible:border-pulsar"
    >
      <svg width={W} height={H} aria-hidden className="shrink-0">
        {sky.links.map(([a, b], i) => {
          const p = drawn[a];
          const q = drawn[b];
          if (!p || !q) return null;
          return (
            <motion.line
              key={i}
              x1={p.x}
              y1={p.y}
              x2={q.x}
              y2={q.y}
              stroke="var(--color-pulsar)"
              strokeWidth={0.8}
              variants={{ rest: { opacity: 0.25 }, hover: { opacity: 0.8 } }}
              transition={{ ...springSnappy, delay: i * 0.025 }}
            />
          );
        })}
        {drawn.map((p, i) => {
          const state = p.box === null ? null : (health[p.box] ?? "absent");
          return (
            <motion.circle
              key={i}
              cx={p.x}
              cy={p.y}
              fill={state ? NODE_FILL[state] : "var(--color-halo)"}
              variants={{
                rest: { r: state ? 2.2 : 1.4 },
                hover: { r: state ? 3.2 : 1.4 },
              }}
              transition={{ ...springSnappy, delay: i * 0.03 }}
            />
          );
        })}
        {/* The arrival's rings, previewed: one per bound box, on hover. */}
        {drawn.map((p, i) =>
          p.box === null ? null : (
            <motion.circle
              key={`ring-${i}`}
              cx={p.x}
              cy={p.y}
              fill="none"
              stroke="var(--color-pulsar)"
              strokeWidth={0.8}
              variants={{ rest: { r: 2, opacity: 0 }, hover: { r: 6, opacity: 0.6 } }}
              transition={{ ...springSnappy, delay: 0.08 + i * 0.03 }}
            />
          ),
        )}
      </svg>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1 text-[12.5px] font-medium text-starlight">
          Command all boxes
          <ArrowRight
            size={12}
            strokeWidth={1.75}
            className="text-static transition-transform group-hover:translate-x-0.5 group-hover:text-pulsar"
          />
        </span>
        <span className="mt-0.5 block text-[10.5px] leading-snug text-static">
          Every debug control, sent to the whole constellation at once.
        </span>
      </span>
    </motion.button>
  );
}
