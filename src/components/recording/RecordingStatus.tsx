import { CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { clockSpan } from "@/components/sessions/BoxStatus";
import { useIntanStatus } from "@/lib/intan/context";
import type { IntanStatus } from "@/lib/intan/types";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

/**
 * What RHX is doing right now, as one block: the state chip, the elapsed
 * clock, the run's name, whatever RHX has to say, the graceful end's progress,
 * and the per-box sync check. Mission Control's rail wraps it in glass; the
 * Recording tab's Live tile mounts it inside a `HudTile`. One component,
 * because the two surfaces answer the same question and a second copy is how
 * they would start answering it differently.
 */

const STATE_LABEL: Record<IntanStatus["state"], string> = {
  disconnected: "RHX not connected",
  idle: "Not recording",
  configured: "Armed — starts with the first box",
  recording: "Recording",
  stopping: "Finishing the trials in flight",
  error: "Recording problem",
};

const CHIP: Record<IntanStatus["state"], { text: string; color: string }> = {
  disconnected: { text: "NO RHX", color: "var(--color-status-error)" },
  idle: { text: "IDLE", color: "var(--color-static)" },
  configured: { text: "ARMED", color: "var(--color-status-warning)" },
  // Ion, not red: this app's "connected / nominal" colour, and a recording
  // that is recording is exactly that. No glow, per the accent's rule.
  recording: { text: "REC", color: "var(--color-ion)" },
  stopping: { text: "ENDING", color: "var(--color-status-warning)" },
  error: { text: "ERROR", color: "var(--color-status-error)" },
};

/** RHX's state as a chip — `StateChip`'s exact styling, so a recording reads
 *  the way a box does one tile over. */
export function RecChip({ state }: { state: IntanStatus["state"] }) {
  const chip = CHIP[state];
  return (
    <span
      className="shrink-0 rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[10px] tracking-wide"
      style={{ color: chip.color }}
    >
      {chip.text}
    </span>
  );
}

export function RecordingStatus() {
  const intan = useIntanStatus();
  const { client } = useSidecar();
  const reduceMotion = useReduceMotion();
  const run = intan.recording;
  const elapsed = useElapsed(intan.state === "recording" ? (run?.startedAt ?? null) : null);
  const tone = CHIP[intan.state].color;
  const live = intan.state === "recording" || intan.state === "stopping";

  return (
    <div>
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className={`size-2 shrink-0 rounded-full ${
            intan.state === "recording" && !reduceMotion ? "animate-pulse" : ""
          }`}
          style={{ background: tone }}
        />
        <RecChip state={intan.state} />
        <span className="truncate text-[13px] font-medium text-starlight">{STATE_LABEL[intan.state]}</span>
        {elapsed && (
          <span className="ml-auto font-mono text-[12px] tabular-nums text-static">{elapsed}</span>
        )}
      </div>

      {run && (
        <div className="mt-2 font-mono text-[11px] leading-relaxed break-all" data-selectable title={run.path}>
          <span className="text-starlight">
            {run.baseFilename}
            {run.fileTimestamp ? `_${run.fileTimestamp}` : ""}
          </span>
          <span className="text-static"> · {run.fileFormat} · {run.sampleRate / 1000} kS/s</span>
        </div>
      )}

      {intan.message && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed" style={{ color: tone }}>
          <CircleAlert size={13} strokeWidth={1.75} className="mt-px shrink-0" />
          {intan.message}
        </p>
      )}

      {/* The graceful end: each box is finishing the trial it is in, so its
          last outcome lands inside the recording. The operator can cut it. */}
      {intan.state === "stopping" && intan.waitingOn.length > 0 && (
        <div className="mt-2.5 flex items-center justify-between gap-2">
          <span className="text-[11px] text-static">
            Waiting for box {intan.waitingOn.join(", ")} to finish its trial…
          </span>
          <Button
            variant="outline"
            title="Stop RHX now, without waiting for the boxes' trials to finish"
            onClick={() => void client.call(CMD.INTAN_FORCE_STOP, {})}
          >
            End now
          </Button>
        </div>
      )}

      {/* The wiring check. A box whose strobes are arriving with no edge to
          match them has a sync line that is not reaching its digital input.
          Synthetic data drives no sync line, so there is nothing to check. */}
      {live && intan.synthetic && (
        <p className="mt-2.5 border-t border-halo pt-2 font-mono text-[10px] text-static">
          sync check off · synthetic data · events aligned by arrival
        </p>
      )}
      {intan.sync.length > 0 && (
        <div className="mt-2.5 border-t border-halo pt-2">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-static/70">sync check</div>
          <div className="grid grid-cols-[auto_auto_1fr_1fr_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px] tabular-nums">
            <span className="text-[10px] text-static/70">box</span>
            <span className="text-[10px] text-static/70">din</span>
            <span className="text-right text-[10px] text-static/70">matched</span>
            <span className="text-right text-[10px] text-static/70">missed</span>
            <span className="text-right text-[10px] text-static/70">stray</span>
            {intan.sync.map((stat) => {
              const dead = stat.matched === 0 && stat.unmatchedStrobes > 3;
              const din = run?.boxes.find((b) => b.box === stat.box)?.digitalIn;
              const color = dead ? "var(--color-status-error)" : undefined;
              return (
                <RowOf key={stat.box} color={color}>
                  <span>{stat.box}</span>
                  <span>{din ?? "—"}</span>
                  {dead ? (
                    <span className="col-span-3 text-right">no pulses arriving — check the sync line</span>
                  ) : (
                    <>
                      <span className="text-right text-starlight">{stat.matched}</span>
                      <span className="text-right">{stat.unmatchedStrobes}</span>
                      <span className="text-right">{stat.spuriousEdges}</span>
                    </>
                  )}
                </RowOf>
              );
            })}
          </div>
        </div>
      )}

      {!intan.liveStreams && (intan.state === "recording" || intan.state === "configured") && (
        <p className="mt-2 text-[11px] leading-relaxed text-static">
          Live views are unavailable — RHX's data sockets did not open. The recording itself is unaffected.
        </p>
      )}
    </div>
  );
}

/** One grid row, coloured as a unit. `display: contents` keeps the cells in
 *  the parent grid while a single colour covers all of them. */
function RowOf({ color, children }: { color: string | undefined; children: React.ReactNode }) {
  return (
    <span className="contents text-static" style={color ? { color } : undefined}>
      {children}
    </span>
  );
}

function useElapsed(startedAt: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  if (!startedAt) return null;
  return clockSpan(Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000)));
}
