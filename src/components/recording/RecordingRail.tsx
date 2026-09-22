import { Activity, AudioWaveform, ChartColumn, Grid2x2 } from "lucide-react";

import { Button } from "@/components/common/controls";
import { useIntanStatus } from "@/lib/intan/context";
import type { ScopeKind } from "@/lib/intan/types";
import { openScopeWindow, type ScopeTrigger } from "@/lib/intan/windows";

import { RecordingStatus } from "./RecordingStatus";

/**
 * Mission Control's recording surfaces (`recording.md` §7): the rail block that
 * says what RHX is doing, and the row of buttons on each recorded box that
 * opens its live views.
 *
 * Both render NOTHING for a behavior-only session — a recording is an addition
 * to Mission Control, not a mode of it. The block's body is `RecordingStatus`,
 * shared with the Recording tab's Live tile; the rail only supplies the glass.
 */
export function RecordingRail() {
  return (
    <section className="hud rounded-md p-3.5">
      <RecordingStatus />
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
  const first = mine.channels[0];
  const last = mine.channels[mine.channels.length - 1];

  return (
    <div className="mt-3 border-t border-halo pt-2.5">
      <div className="font-mono text-[10px] text-static">
        port {mine.port} · DIN {mine.digitalIn}
        {first ? ` · ${first}${last && last !== first ? `…${last}` : ""}` : ""}
      </div>
      {/* Ghost, not outline: four outlined buttons in a 344px rail read as a
          toolbar competing with the Start/Stop row above them. */}
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {SCOPES.filter((s) => s.kind !== "probemap" || mine.probeMap !== null).map(({ kind, label, Icon }) => (
          <Button
            key={kind}
            variant="ghost"
            disabled={!intan.liveStreams}
            title={
              intan.liveStreams
                ? `Open ${label} for box ${box} in its own window`
                : "Live views unavailable — RHX's data sockets did not open"
            }
            onClick={() => openScopeWindow(kind, box, { animal: animalName, triggers })}
          >
            <Icon size={12} strokeWidth={1.75} />
            {label}
          </Button>
        ))}
      </div>
    </div>
  );
}
