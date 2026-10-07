import type { ReactNode } from "react";

/**
 * A telemetry panel's name (`ARCHITECTURE.md#telemetry-panels`): the subject in
 * tracked mono capitals, the way an instrument labels a readout, and the
 * plain-language note beside it in the UI face so it still reads as a
 * sentence. One component, so every panel on the display names itself the
 * same way.
 */
export function PanelTitle({ name, note }: { name: string; note?: ReactNode }) {
  return (
    <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
      <span className="font-mono text-[10px] tracking-[0.16em] text-starlight uppercase">
        {name}
      </span>
      {note && <span className="text-[11px] text-static/70">{note}</span>}
    </span>
  );
}
