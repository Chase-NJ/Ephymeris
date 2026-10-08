import { AnimatePresence, motion, useMotionValueEvent, useSpring } from "framer-motion";
import { RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { ConfigFields } from "@/components/sessions/ConfigFields";
import { PANEL_TRAVEL, springSnappy } from "@/lib/motion";
import { isRowOwnedField } from "@/lib/taskdef/lines";
import { inactiveNote } from "@/lib/taskdef/selection";
import type { SelectionMode, StageRow, TaskDiagnostic } from "@/lib/taskdef/types";
import {
  accumulateWheel,
  orbitPoint,
  planetAt,
  upperArc,
  type OrbitGeometry,
} from "@/lib/tasks/orrery";
import {
  HOLDS_TAB,
  dialTabs,
  groupsOfTab,
  nodesGovernedByTab,
  tabOf,
  type TaskGraphModel,
} from "@/lib/tasks/topology";
import { useElementWidth } from "@/lib/useElementWidth";
import { useReduceMotion } from "@/lib/useReduceMotion";
import type { TaskProfile } from "@/lib/ws/protocol";

import { Panel } from "./Panel";
import { StageList } from "./StageList";

/** The dial's drawn height. */
const DIAL_H = 112;
/** Wheel steps are locked this long after one lands, against trackpad inertia. */
const WHEEL_LOCK_MS = 220;

/**
 * The parameter dial (`TASKS.md#parameter-dial`): the task's categories as
 * planets on an orbit, turned to bring one to the zenith, its fields below.
 *
 * Stops are `dialTabs` — Session, Trial timing, Holds & shaping, Abstention
 * penalty, and any group a future profile invents. Trial generation and the
 * row-owned volumes have homes of their own on the page.
 *
 * The orbit turns on ONE spring (`phase`, the fractional index at the zenith),
 * and every planet is placed from it each frame, so the planets travel along
 * the arc together rather than sliding in straight lines. Flat throughout: a
 * selected planet is filled Pulsar, a lit one is ringed, nothing glows.
 */
export function ParameterOrrery({
  profile,
  model,
  config,
  baseline,
  mode,
  stages,
  diagnostics,
  selected,
  litGroups,
  onSelect,
  onParams,
  onStages,
  onHoverGroup,
}: {
  profile: TaskProfile | null;
  model: TaskGraphModel;
  config: Record<string, unknown>;
  baseline: Record<string, unknown>;
  mode: SelectionMode;
  stages: StageRow[];
  diagnostics: TaskDiagnostic[];
  selected: string | null;
  /** Raw groups governing the state under the pointer — they light planets. */
  litGroups: ReadonlySet<string>;
  onSelect: (tab: string) => void;
  onParams: (next: Record<string, unknown>) => void;
  onStages: (next: StageRow[]) => void;
  onHoverGroup: (tab: string | null) => void;
}) {
  const declared = useMemo(
    () => new Set((profile?.config ?? []).map((f) => f.group).filter(Boolean) as string[]),
    [profile],
  );
  const tabs = useMemo(() => {
    const out = dialTabs(declared);
    // The ramp is always the definition's, profile or not.
    return out.includes(HOLDS_TAB) ? out : [...out, HOLDS_TAB];
  }, [declared]);
  const active = selected && tabs.includes(selected) ? selected : (tabs[0] ?? HOLDS_TAB);
  const index = Math.max(0, tabs.indexOf(active));

  // Direction of travel, for the fields' slide.
  const previous = useRef(index);
  const direction = index === previous.current ? 0 : index > previous.current ? 1 : -1;
  useEffect(() => {
    previous.current = index;
  }, [index]);

  const pinned = (tab: string) =>
    (profile?.config ?? []).some(
      (f) =>
        f.group &&
        tabOf(f.group) === tab &&
        !isRowOwnedField(f.metadataKey) &&
        !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
    );
  const troubled = (tab: string) =>
    tab === HOLDS_TAB && diagnostics.some((d) => d.location.startsWith("stages"));

  const members = groupsOfTab(active, declared);
  const changed = (profile?.config ?? []).filter(
    (f) =>
      f.group &&
      members.includes(f.group) &&
      !isRowOwnedField(f.metadataKey) &&
      !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
  );
  const states = nodesGovernedByTab(model, active).map((n) => n.label);

  return (
    <Panel
      id="params"
      name="Parameters"
      note="turn the dial — click, arrows or scroll"
      className="flex-1"
      bodyClassName="gap-2"
    >
      <OrreryDial
        tabs={tabs}
        index={index}
        litGroups={litGroups}
        pinned={pinned}
        troubled={troubled}
        onSelect={onSelect}
        onHoverGroup={onHoverGroup}
      />

      <div className="flex items-start gap-2 border-b border-halo/60 pb-1.5">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] tracking-[0.16em] text-starlight uppercase">{active}</div>
          {states.length > 0 && (
            <div className="truncate font-mono text-[9.5px] text-static/70" title={states.join(" · ")}>
              tunes {states.join(" · ")}
            </div>
          )}
        </div>
        {changed.length > 0 && (
          <button
            type="button"
            onClick={() => {
              const next = { ...config };
              for (const f of changed) next[f.metadataKey] = baseline[f.metadataKey];
              onParams(next);
            }}
            className="flex shrink-0 items-center gap-1 text-[10px] text-static transition-colors hover:text-starlight"
          >
            <RotateCcw size={10} strokeWidth={1.75} />
            Reset {changed.length}
          </button>
        )}
      </div>

      <div
        id="parameter-fields"
        role="tabpanel"
        className="scrollbar-slim relative -mr-2 min-h-0 flex-1 overflow-x-hidden overflow-y-auto pr-2"
      >
        <AnimatePresence mode="popLayout" initial={false} custom={direction}>
          <motion.div
            key={active}
            custom={direction}
            variants={{
              enter: (d: number) => ({ opacity: 0, x: d * PANEL_TRAVEL }),
              shown: { opacity: 1, x: 0 },
              leave: (d: number) => ({ opacity: 0, x: -d * PANEL_TRAVEL }),
            }}
            initial="enter"
            animate="shown"
            exit="leave"
            transition={springSnappy}
          >
            {active === HOLDS_TAB ? (
              <StageList stages={stages} diagnostics={diagnostics} onChange={onStages} />
            ) : (
              <ConfigFields
                profile={profile}
                config={config}
                baseline={baseline}
                onChange={onParams}
                only={members}
                quiet
                fieldFilter={(f) => !isRowOwnedField(f.metadataKey)}
                inactive={(f) => inactiveNote(mode, f)}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </Panel>
  );
}

/**
 * The orbit itself. Planets are real buttons — a `tablist` with a roving tab
 * stop — laid over the drawing, so the dial is a keyboard control and not a
 * picture of one.
 */
function OrreryDial({
  tabs,
  index,
  litGroups,
  pinned,
  troubled,
  onSelect,
  onHoverGroup,
}: {
  tabs: string[];
  index: number;
  litGroups: ReadonlySet<string>;
  pinned: (tab: string) => boolean;
  troubled: (tab: string) => boolean;
  onSelect: (tab: string) => void;
  onHoverGroup: (tab: string | null) => void;
}) {
  const reduceMotion = useReduceMotion();
  const [host, width] = useElementWidth<HTMLDivElement>();
  const w = width ?? 320;
  const orbit: OrbitGeometry = { cx: w / 2, cy: DIAL_H - 30, rx: Math.min(150, w / 2 - 34), ry: 50 };
  const n = tabs.length;

  // The one spring the whole orbit turns on. It starts a step and a half
  // short of the selection and sweeps in on mount.
  const phase = useSpring(reduceMotion ? index : index - 1.5, {
    stiffness: 320,
    damping: 34,
    mass: 0.9,
  });
  const [now, setNow] = useState(phase.get());
  useMotionValueEvent(phase, "change", setNow);
  useEffect(() => {
    if (reduceMotion) {
      phase.jump(index);
      setNow(index);
    } else phase.set(index);
  }, [index, phase, reduceMotion]);

  const [hover, setHover] = useState<number | null>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  const go = (next: number, focus: boolean) => {
    const clamped = Math.max(0, Math.min(n - 1, next));
    const tab = tabs[clamped];
    if (!tab) return;
    onSelect(tab);
    if (focus) buttons.current[clamped]?.focus();
  };

  function onKey(event: KeyboardEvent) {
    const to =
      event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? index - 1
        : event.key === "ArrowRight" || event.key === "ArrowDown"
          ? index + 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? n - 1
              : null;
    if (to === null) return;
    event.preventDefault();
    go(to, true);
  }

  // The wheel turns the dial one stop per gesture. Native and non-passive:
  // React's onWheel cannot preventDefault, and the page must not scroll while
  // the pointer is on the dial.
  const latest = useRef({ index, go });
  latest.current = { index, go };
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let pending = 0;
    let lockedUntil = 0;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const nowMs = performance.now();
      if (nowMs < lockedUntil) return;
      const r = accumulateWheel(pending, event.deltaY + event.deltaX);
      pending = r.pending;
      if (r.stops !== 0) {
        lockedUntil = nowMs + WHEEL_LOCK_MS;
        latest.current.go(latest.current.index + Math.sign(r.stops), false);
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [host]);

  const zenith = orbitPoint(90, orbit);
  const ticks = Array.from({ length: 13 }, (_, i) => i * 15);

  return (
    <div ref={host} className="relative select-none" style={{ height: DIAL_H }}>
      <svg width={w} height={DIAL_H} className="absolute inset-0" aria-hidden>
        {/* The horizon, with end ticks. */}
        <line
          x1={orbit.cx - orbit.rx - 10}
          x2={orbit.cx + orbit.rx + 10}
          y1={orbit.cy}
          y2={orbit.cy}
          stroke="var(--color-halo)"
          strokeWidth={1}
        />
        {[-1, 1].map((side) => (
          <line
            key={side}
            x1={orbit.cx + side * (orbit.rx + 10)}
            x2={orbit.cx + side * (orbit.rx + 10)}
            y1={orbit.cy - 3}
            y2={orbit.cy + 3}
            stroke="var(--color-halo)"
          />
        ))}
        {/* The orbit's drawn half, and its reticle every 15°. */}
        <path d={upperArc(orbit)} fill="none" stroke="var(--color-halo)" strokeWidth={1} />
        {ticks.map((deg) => {
          const a = orbitPoint(deg, orbit);
          const b = orbitPoint(deg, { ...orbit, rx: orbit.rx + 5, ry: orbit.ry + 5 });
          return (
            <line
              key={deg}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="var(--color-static)"
              strokeOpacity={deg % 45 === 0 ? 0.55 : 0.25}
            />
          );
        })}
        {/* The zenith: a fixed caret and plumb line the orbit turns under. */}
        <path
          d={`M ${zenith.x - 4} ${zenith.y - 20} L ${zenith.x + 4} ${zenith.y - 20} L ${zenith.x} ${zenith.y - 14} Z`}
          fill="var(--color-pulsar)"
        />
        <line
          x1={zenith.x}
          x2={zenith.x}
          y1={zenith.y - 13}
          y2={zenith.y - 9}
          stroke="var(--color-pulsar)"
          strokeOpacity={0.6}
        />
        {/* The planets, placed from the spring's current phase. */}
        {tabs.map((tab, i) => {
          const at = planetAt(i, now, n, orbit);
          const r = 3 + 4 * at.height;
          const isActive = i === index;
          const lit = hover === i || [...litGroups].some((g) => tabOf(g) === tab);
          const labelOpacity = isActive ? 1 : Math.max(0, Math.min(1, at.height * 1.4 - 0.25));
          return (
            <g key={tab}>
              {lit && !isActive && (
                <circle cx={at.x} cy={at.y} r={r + 4} fill="none" stroke="var(--color-pulsar)" strokeWidth={1} />
              )}
              {troubled(tab) && (
                <circle cx={at.x} cy={at.y} r={r + 2.5} fill="none" stroke="var(--color-status-error)" strokeWidth={1} />
              )}
              <circle
                cx={at.x}
                cy={at.y}
                r={r}
                fill={isActive ? "var(--color-pulsar)" : lit ? "var(--color-starlight)" : "var(--color-nebula)"}
                stroke={isActive ? "var(--color-pulsar)" : "var(--color-static)"}
                strokeOpacity={isActive ? 1 : 0.4 + 0.5 * at.height}
                strokeWidth={1}
                style={{ transition: "fill 160ms" }}
              />
              {pinned(tab) && (
                <circle cx={at.x + r + 3.5} cy={at.y - r} r={1.6} fill="var(--color-pulsar)" />
              )}
              <text
                x={at.x}
                y={at.y + r + 11}
                textAnchor="middle"
                className="font-mono"
                fontSize={9}
                fill={isActive || lit ? "var(--color-starlight)" : "var(--color-static)"}
                opacity={labelOpacity}
              >
                {short(tab)}
              </text>
            </g>
          );
        })}
      </svg>

      <div role="tablist" aria-label="Parameter categories" onKeyDown={onKey} className="absolute inset-0">
        {tabs.map((tab, i) => {
          const at = planetAt(i, now, n, orbit);
          return (
            <button
              key={tab}
              ref={(el) => {
                buttons.current[i] = el;
              }}
              type="button"
              role="tab"
              aria-selected={i === index}
              aria-controls="parameter-fields"
              aria-label={tab}
              tabIndex={i === index ? 0 : -1}
              onClick={() => go(i, false)}
              onPointerEnter={() => {
                setHover(i);
                onHoverGroup(tab);
              }}
              onPointerLeave={() => {
                setHover(null);
                onHoverGroup(null);
              }}
              onFocus={() => onHoverGroup(tab)}
              onBlur={() => onHoverGroup(null)}
              className="absolute size-7 -translate-x-1/2 -translate-y-1/2 rounded-full focus:outline-none focus-visible:ring-1 focus-visible:ring-pulsar"
              style={{ left: at.x, top: at.y }}
            />
          );
        })}
      </div>
    </div>
  );
}

/** A planet's label: the chip vocabulary the machine already uses. */
function short(tab: string): string {
  const known: Record<string, string> = {
    Session: "session",
    "Trial timing": "timing",
    [HOLDS_TAB]: "holds",
    "Abstention penalty": "penalty",
  };
  return known[tab] ?? tab.toLowerCase();
}
