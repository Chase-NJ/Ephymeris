import { Activity, AudioWaveform, ChartColumn, CircleAlert, Grid2x2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { useIntanStatus } from "@/lib/intan/context";
import type { IntanStatus, ScopeKind } from "@/lib/intan/types";
import { openScopeWindow, type ScopeTrigger } from "@/lib/intan/windows";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

/**
 * Mission Control's recording surfaces (`recording.md` §7): the rail block that
 * says what RHX is doing, and the row of buttons on each recorded box that
 * opens its live views.
 *
 * Both render NOTHING for a behavior-only session — a recording is an addition
 * to Mission Control, not a mode of it.
 */

const STATE_LABEL: Record<IntanStatus["state"], string> = {
  disconnected: "RHX not connected",
  idle: "Not recording",
  configured: "Armed — starts with the first box",
  recording: "Recording",
  stopping: "Finishing",
  error: "Recording problem",
};

export function RecordingRail() {
  const intan = useIntanStatus();
  const { client } = useSidecar();
  const run = intan.recording;
  const elapsed = useElapsed(intan.state === "recording" ? (run?.startedAt ?? null) : null);

  const tone =
    intan.state === "error" || intan.state === "disconnected"
      ? "var(--color-status-error)"
      : intan.state === "recording"
        ? "var(--color-ion)"
        : intan.state === "stopping"
          ? "var(--color-status-warning)"
          : "var(--color-static)";

  return (
    <section className="hud rounded-md p-3.5">
      <div className="flex items-center gap-2">
        {/* Flat and matte, like every status dot in the app: no glow, and the
            only motion is the opacity pulse the theme already uses. */}
        <span
          aria-hidden
          className={`size-2 shrink-0 rounded-full ${intan.state === "recording" ? "animate-pulse" : ""}`}
          style={{ background: tone }}
        />
        <span className="text-[13px] font-medium text-starlight">{STATE_LABEL[intan.state]}</span>
        {elapsed && <span className="ml-auto font-mono text-[12px] text-static">{elapsed}</span>}
      </div>

      {run && (
        <div className="mt-2 font-mono text-[11px] leading-relaxed break-all text-static" data-selectable>
          {run.baseFilename}
          {run.fileTimestamp ? `_${run.fileTimestamp}` : ""}
          <span className="text-static/70">
            {" "}
            · {run.fileFormat} · {run.sampleRate / 1000} kS/s
          </span>
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
          <Button variant="outline" onClick={() => void client.call(CMD.INTAN_FORCE_STOP, {})}>
            End now
          </Button>
        </div>
      )}

      {/* Synthetic data (RHX's demo, no controller) drives no sync line, so
          the sidecar publishes no counters; say why rather than show nothing. */}
      {intan.synthetic && (intan.state === "recording" || intan.state === "stopping") && (
        <p className="mt-2.5 border-t border-halo pt-2 font-mono text-[11px] text-static">
          synthetic data · sync line check off · events aligned by arrival
        </p>
      )}

      {/* The wiring check. A box whose strobes are arriving with no edge to
          match them has a sync line that is not reaching its digital input. */}
      {intan.sync.length > 0 && (
        <ul className="mt-2.5 flex flex-col gap-0.5 border-t border-halo pt-2">
          {intan.sync.map((stat) => {
            const dead = stat.matched === 0 && stat.unmatchedStrobes > 3;
            return (
              <li key={stat.box} className="flex items-center justify-between font-mono text-[11px] text-static">
                <span>box {stat.box} sync</span>
                <span style={dead ? { color: "var(--color-status-error)" } : undefined}>
                  {dead
                    ? "no pulses arriving — check the sync line"
                    : `${stat.matched} matched${
                        stat.unmatchedStrobes ? ` · ${stat.unmatchedStrobes} missed` : ""
                      }${stat.spuriousEdges ? ` · ${stat.spuriousEdges} stray` : ""}`}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {!intan.liveStreams && (intan.state === "recording" || intan.state === "configured") && (
        <p className="mt-2 text-[11px] leading-relaxed text-static">
          Live views are unavailable — RHX's data sockets did not open. The recording itself is unaffected.
        </p>
      )}
    </section>
  );
}

const SCOPES: { kind: ScopeKind; label: string; Icon: typeof Activity }[] = [
  { kind: "spikescope", label: "Spike Scope", Icon: AudioWaveform },
  { kind: "psth", label: "PSTH", Icon: ChartColumn },
  { kind: "isi", label: "ISI", Icon: Activity },
  { kind: "probemap", label: "Probe map", Icon: Grid2x2 },
];

/** The four pop-ups, for one recorded box. Renders nothing otherwise. */
export function ScopeButtons({
  box,
  animalName,
  triggers,
}: {
  box: number;
  animalName: string;
  /** This box's strobe vocabulary — what a PSTH can be aligned to. */
  triggers: ScopeTrigger[];
}) {
  const intan = useIntanStatus();
  const mine = intan.recording?.boxes.find((b) => b.box === box);
  if (!mine) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-halo pt-3">
      {SCOPES.filter((s) => s.kind !== "probemap" || mine.probeMap !== null).map(({ kind, label, Icon }) => (
        <Button
          key={kind}
          variant="outline"
          title={`Open ${label} for box ${box} in its own window`}
          onClick={() => openScopeWindow(kind, box, { animal: animalName, triggers })}
        >
          <Icon size={12} strokeWidth={1.75} />
          {label}
        </Button>
      ))}
      <span className="ml-auto font-mono text-[10px] text-static">
        port {mine.port} · DIN {mine.digitalIn}
      </span>
    </div>
  );
}

function useElapsed(startedAt: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  if (!startedAt) return null;
  const seconds = Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
