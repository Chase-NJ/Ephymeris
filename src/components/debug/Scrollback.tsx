import { useEffect, useRef } from "react";

import type { ConsoleLine } from "@/lib/hardware/store";

/**
 * The console scrollback (`dashboard.md` §6.3): batched output with
 * sent commands interleaved, pinned to the bottom only while the user is at
 * the bottom — scrolling up to read must not be fought by the autoscroll.
 *
 * Extracted from the old ConsolePanel so the node detail view could reorganize
 * the console without duplicating the pinning logic.
 */

/** Pin-to-bottom tolerance: within this many px of the end counts as "at" it. */
const PIN_THRESHOLD_PX = 24;

/**
 * A sketch's live telemetry lines (`tasks.md` §3.5): received lines
 * beginning with the profile's `telemetry.match`, conventionally `STATUS`.
 *
 * These are emitted on every state change *plus* a ~1 s heartbeat, so on a
 * chatty utility sketch they outnumber everything else several-to-one. That is
 * the whole reason the console splits them out: interleaved, they bury the
 * command echoes and error text you actually opened the console to read.
 */
export function isStatusLine(line: ConsoleLine, match: string): boolean {
  return line.dir === "rx" && line.text.trimStart().startsWith(match);
}

/** The default `telemetry.match`, for a sketch with no profile to declare one. */
export const DEFAULT_STATUS_MATCH = "STATUS";

export function Scrollback({
  lines,
  className = "h-44",
  emptyLabel = "— no output —",
}: {
  lines: ConsoleLine[];
  className?: string;
  emptyLabel?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div
      ref={ref}
      data-selectable
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < PIN_THRESHOLD_PX;
      }}
      className={`${className} overflow-y-auto bg-void/60 px-2.5 py-1.5 font-mono text-[11px] leading-[1.65]`}
    >
      {lines.length === 0 ? (
        <span className="text-static/50">{emptyLabel}</span>
      ) : (
        lines.map((l) => (
          <div key={l.id} className="flex gap-2 break-all whitespace-pre-wrap">
            <span className="shrink-0 text-static/60">{formatTs(l.ts)}</span>
            <span className="w-2 shrink-0 text-pulsar">{l.dir === "tx" ? "›" : ""}</span>
            <span className={l.dir === "tx" ? "text-pulsar" : "text-starlight"}>
              {l.text || " "}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

export function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}
