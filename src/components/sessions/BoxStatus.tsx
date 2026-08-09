import { useEffect, useState } from "react";

/**
 * The small per-box status pieces `BoxCard` and `StarPanel` share — the tile
 * and the panel are one object at two sizes (`MissionControl`), so their state
 * chip and run clock have to be literally the same components or the two
 * eventually disagree.
 */

/**
 * One box's run clock (`dashboard.md` §5.4): elapsed since *this box's* start,
 * against the session's optional time limit. Driven by the snapshot's
 * `startedAt` rather than a client-side stopwatch, so a reloaded window
 * resumes mid-count. Once time is up the sidecar has already sent STOP — the
 * line says so instead of counting on, because the run now ends at the
 * board's next trial boundary.
 */
export function ElapsedClock({
  startedAt,
  live,
  durationMinutes,
}: {
  startedAt: string | null;
  live: boolean;
  durationMinutes: number | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live || !startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live, startedAt]);

  if (!live || !startedAt) return null;
  const elapsed = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const limit = durationMinutes !== null ? durationMinutes * 60 : null;
  const timeUp = limit !== null && elapsed >= limit;

  return (
    <div
      className="mt-1 font-mono text-[11px] tabular-nums text-static"
      style={timeUp ? { color: "var(--color-status-warning)" } : undefined}
    >
      {clockSpan(elapsed)}
      {limit !== null && ` / ${clockSpan(limit)}`}
      {timeUp && " · time up — stopping at the next trial boundary"}
    </div>
  );
}

/** Seconds as m:ss, growing to h:mm:ss for long sessions. */
export function clockSpan(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export function StateChip({ state, reason }: { state: string; reason: string }) {
  const color =
    state === "IN_SESSION"
      ? "var(--color-status-ok)"
      : state === "ERROR"
        ? "var(--color-status-error)"
        : "var(--color-static)";
  return (
    <span
      title={reason}
      className="shrink-0 rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[10px]"
      style={{ color }}
    >
      {state}
    </span>
  );
}
