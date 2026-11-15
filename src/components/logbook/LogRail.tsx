import { motion } from "framer-motion";
import { Flag } from "lucide-react";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { SessionListItem } from "@/lib/analytics/types";
import { springSnappy } from "@/lib/motion";
import { isoOfDay, layoutRail, monthJump, ROW_PX, stepFrom } from "@/lib/logbook/rail";
import { useReduceMotion } from "@/lib/useReduceMotion";

/** Where the read head sits, as a fraction of the rail's height. */
const HEAD_AT = 0.36;
/** Wheel travel per step — a notch on a mouse, a short flick on a trackpad. */
const WHEEL_STEP = 48;
/** Left edge of the spine: the date gutter sits to its left. */
const SPINE_X = 64;

/**
 * The flight recorder: a cohort's sessions on a tape that moves past a fixed
 * read head (`USER-GUIDE.md#keeping-the-log`).
 *
 * Spaced by real days, newest at the top (`lib/logbook/rail.ts`), so weekends
 * and missed days read as distance. The selected session always sits at the
 * head; stepping moves the tape, not a highlight — so the eye stays in one
 * place while the history slides under it, and what's just before and after
 * the selection is always in view around it.
 *
 * A listbox to assistive tech: one focus stop, `aria-activedescendant` for
 * the current session, arrows and j/k to step, Page Up/Down by month,
 * Home/End to the ends.
 *
 * **A step must stay cheap**, because a trackpad flick fires dozens of them.
 * The rail is memoized (the Log's deferred render of the session page passes
 * it the same props, so it is skipped), every tick is memoized against a
 * stable `onSelect` (a step re-renders only the two ticks whose selection
 * changed), and dates go through formatters built once — `toLocaleDateString`
 * with options builds a fresh `Intl.DateTimeFormat` on every call, and a
 * hundred of those per step was most of the stutter.
 */
export const LogRail = memo(function LogRail({
  sessions,
  selectedId,
  onSelect,
  noteCounts,
  flagged,
}: {
  sessions: SessionListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  noteCounts: Map<string, number>;
  /** Sessions holding an open carry-forward flag. */
  flagged: Set<string>;
}) {
  const reduce = useReduceMotion();
  const layout = useMemo(() => layoutRail(sessions), [sessions]);
  const byId = useMemo(() => new Map(sessions.map((s) => [s.id, s])), [sessions]);

  const frame = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(480);
  useLayoutEffect(() => {
    const el = frame.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setHeight(entry.contentRect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const head = Math.round(height * HEAD_AT);
  const selectedY = selectedId !== null ? (layout.positions.get(selectedId) ?? 0) : 0;
  const offset = head - selectedY - ROW_PX / 2;

  function step(delta: number) {
    const next = stepFrom(layout.order, selectedId, delta);
    if (next && next !== selectedId) onSelect(next);
  }

  // The wheel listener is attached natively: React's is passive, and the rail
  // must keep a trackpad flick from also scrolling the page behind it.
  const travel = useRef(0);
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      travel.current += event.deltaY;
      if (Math.abs(travel.current) >= WHEEL_STEP) {
        stepRef.current(Math.sign(travel.current));
        travel.current = 0;
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  function onKeyDown(event: React.KeyboardEvent) {
    const keys: Record<string, () => void> = {
      ArrowDown: () => step(1),
      j: () => step(1),
      ArrowUp: () => step(-1),
      k: () => step(-1),
      PageDown: () => jump(monthJump(sessions, selectedId, -1)),
      PageUp: () => jump(monthJump(sessions, selectedId, 1)),
      Home: () => jump(layout.order[0] ?? null),
      End: () => jump(layout.order[layout.order.length - 1] ?? null),
    };
    const action = keys[event.key];
    if (!action || event.metaKey || event.ctrlKey || event.altKey) return;
    event.preventDefault();
    action();
  }

  function jump(id: string | null) {
    if (id && id !== selectedId) onSelect(id);
  }

  // One identity for the life of the rail, so the memoized ticks never see a
  // new handler just because the Log re-rendered.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const select = useCallback((id: string) => onSelectRef.current(id), []);

  return (
    <div
      ref={frame}
      role="listbox"
      tabIndex={0}
      aria-label="Sessions, newest first"
      aria-activedescendant={selectedId ? tickId(selectedId) : undefined}
      onKeyDown={onKeyDown}
      className="relative min-h-0 flex-1 overflow-hidden rounded-md focus-visible:outline-offset-[-2px]"
    >
      {/* The read head: fixed, while the tape moves under it. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 z-10 flex items-center"
        style={{ top: head - ROW_PX / 2, height: ROW_PX }}
      >
        <div className="absolute inset-0 border-y border-pulsar/40 bg-pulsar/[0.07]" />
        <div
          className="absolute size-0 border-y-[5px] border-l-[6px] border-y-transparent border-l-pulsar"
          style={{ left: 0 }}
        />
      </div>

      <motion.div
        className="absolute inset-x-0 top-0"
        style={{ height: layout.height }}
        initial={false}
        animate={{ y: offset }}
        transition={reduce ? { duration: 0 } : springSnappy}
      >
        <div
          aria-hidden
          className="absolute w-px bg-halo"
          style={{ left: SPINE_X, top: ROW_PX / 2, height: Math.max(0, layout.height - ROW_PX) }}
        />

        {layout.items.map((item) => {
          if (item.kind === "empty") {
            return (
              <div
                key={`d${item.day}`}
                aria-hidden
                className="absolute inset-x-0 flex items-center"
                style={{ top: item.y - 6, height: 12 }}
              >
                {item.weekend && <div className="absolute inset-0 bg-halo/25" />}
                <span
                  className="absolute font-mono text-[9px] text-static/45"
                  style={{ right: `calc(100% - ${SPINE_X - 8}px)` }}
                >
                  {item.weekend ? weekdayShort(item.day) : ""}
                </span>
                <span className="absolute h-px w-1.5 bg-halo" style={{ left: SPINE_X - 3 }} />
              </div>
            );
          }
          if (item.kind === "break") {
            return (
              <div
                key={`b${item.y}`}
                className="absolute inset-x-0 flex items-center"
                style={{ top: item.y - 9, height: 18 }}
              >
                <span
                  className="absolute bg-void px-0.5 font-mono text-[11px] leading-none text-static"
                  style={{ left: SPINE_X - 4 }}
                  aria-hidden
                >
                  ≈
                </span>
                <span
                  className="absolute font-mono text-[10px] text-static/80"
                  style={{ left: SPINE_X + 12 }}
                >
                  {item.days} days without a session
                </span>
              </div>
            );
          }
          const session = byId.get(item.id);
          if (!session) return null;
          return (
            <Tick
              key={item.id}
              session={session}
              y={item.y}
              labelsDay={item.labelsDay}
              day={item.day}
              selected={item.id === selectedId}
              notes={noteCounts.get(item.id) ?? 0}
              flagged={flagged.has(item.id)}
              onSelect={select}
            />
          );
        })}
      </motion.div>
    </div>
  );
});

function tickId(sessionId: string): string {
  return `log-tick-${sessionId.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
const MONTH = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });

function weekdayShort(day: number): string {
  return WEEKDAY.format(new Date(day * 86_400_000));
}

const Tick = memo(function Tick({
  session,
  y,
  labelsDay,
  day,
  selected,
  notes,
  flagged,
  onSelect,
}: {
  session: SessionListItem;
  y: number;
  labelsDay: boolean;
  day: number;
  selected: boolean;
  notes: number;
  flagged: boolean;
  onSelect: (id: string) => void;
}) {
  const running = session.status === "running" || session.status === "configuring";
  const aborted = session.status === "aborted";
  const recovered = session.id.startsWith("adopted:");
  const [, month, date] = isoOfDay(day).split("-");
  const name = `${session.prefixName}_${session.sessionNumber}`;

  // The diamond carries status by FILL and the label by weight; colour is only
  // ever state (running) or the selection's accent (`ARCHITECTURE.md#theme`).
  const diamond = selected
    ? "border-pulsar bg-pulsar"
    : running
      ? "border-status-ok bg-status-ok"
      : aborted || recovered
        ? "border-static/60 bg-transparent"
        : "border-static bg-halo";

  return (
    <div
      id={tickId(session.id)}
      role="option"
      aria-selected={selected}
      aria-label={[
        name,
        session.date,
        session.status,
        notes ? `${notes} note${notes === 1 ? "" : "s"}` : null,
        flagged ? "open flag" : null,
      ]
        .filter(Boolean)
        .join(", ")}
      onClick={() => onSelect(session.id)}
      className="group absolute inset-x-0 flex cursor-pointer items-center"
      style={{ top: y, height: ROW_PX }}
    >
      <span
        className={`absolute text-right font-mono text-[10px] leading-tight tabular-nums ${
          selected ? "text-starlight" : "text-static"
        }`}
        style={{ right: `calc(100% - ${SPINE_X - 10}px)` }}
      >
        {labelsDay && (
          <>
            {date} {monthShort(Number(month))}
            <span className="block text-[9px] text-static/70">{weekdayShort(day)}</span>
          </>
        )}
      </span>
      <span
        className={`absolute size-2 rotate-45 border transition-colors ${diamond} ${
          aborted ? "border-dashed" : ""
        }`}
        style={{ left: SPINE_X - 4 }}
      />
      <span
        className="absolute flex min-w-0 items-center gap-1.5 pr-3"
        style={{ left: SPINE_X + 12, right: 0 }}
      >
        <span
          className={`truncate font-mono text-[12px] transition-colors ${
            selected
              ? "text-starlight"
              : aborted || recovered
                ? "text-static/60 group-hover:text-static"
                : "text-static group-hover:text-starlight"
          }`}
        >
          {name}
        </span>
        {running && (
          <span className="shrink-0 font-mono text-[9px] tracking-[0.12em] text-status-ok uppercase">
            live
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {flagged && (
            <Flag size={11} strokeWidth={1.75} className="text-status-warning" aria-hidden />
          )}
          {notes > 0 && (
            <span className="font-mono text-[10px] tabular-nums text-static" aria-hidden>
              {notes}
            </span>
          )}
        </span>
      </span>
    </div>
  );
});

function monthShort(month: number): string {
  return MONTH.format(new Date(Date.UTC(2000, month - 1, 1)));
}
