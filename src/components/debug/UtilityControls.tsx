import { useMemo, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { useBoxOutput } from "@/lib/hardware/context";
import type { Control, TaskProfile, TelemetrySpec } from "@/lib/sessions/types";
import type { ConsoleLine } from "@/lib/hardware/store";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

/**
 * Debug-Mode controls + live status for a **utility** sketch (`data-saving.md`
 * §6.6). Driven entirely by the sketch's Task Profile:
 *
 *  - `controls` render as buttons / selects; each sends its serial command over
 *    the existing `port.send` primitive (no new wire command). Enabled only in
 *    `PASSTHROUGH`, matching the console's own send gate.
 *  - `telemetry` parses the sketch's non-persisted `STATUS` lines out of
 *    `port.output` into a labelled strip. Nothing here is stored — it's live
 *    display only (`websocket-protocol.md` §5.4).
 */
export function UtilityControls({
  box,
  profile,
  canSend,
}: {
  box: number;
  profile: TaskProfile;
  canSend: boolean;
}) {
  const { client } = useSidecar();
  const lines = useBoxOutput(box);

  const controls = profile.controls ?? [];
  const telemetry = profile.telemetry ?? null;

  const status = useMemo(() => parseLatestStatus(lines, telemetry), [lines, telemetry]);

  if (controls.length === 0 && !telemetry) return null;

  function send(command: string) {
    // Fire-and-forget; a rejection (e.g. not in PASSTHROUGH) surfaces as a
    // tx/rx line in the console below, same as any manual send.
    void client.call(CMD.PORT_SEND, { box, text: command, lineEnding: "lf" });
  }

  return (
    <div className="border-t border-halo px-2.5 py-2">
      {controls.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {controls.map((c) =>
            c.type === "select" ? (
              <SelectControl key={c.id} control={c} disabled={!canSend} onSend={send} />
            ) : (
              <Button
                key={c.id}
                onClick={() => c.command && send(c.command)}
                disabled={!canSend || !c.command}
                title={canSend ? (c.command ?? c.label) : "Open passthrough to control"}
              >
                {c.label}
              </Button>
            ),
          )}
        </div>
      )}

      {telemetry && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          {telemetry.fields.map((f) => {
            const value = status?.[f.key];
            if (value === undefined) return null;
            return (
              <span key={f.key} className="font-mono text-[11px]">
                <span className="text-static">{f.label}:</span>{" "}
                <span className="text-starlight">{value}</span>
              </span>
            );
          })}
          {!hasAnyField(status, telemetry) && (
            <span className="text-[11px] text-static/50">— no status yet —</span>
          )}
        </div>
      )}
    </div>
  );
}

/** A `select` control: choosing an option sends that option's command. */
function SelectControl({
  control,
  disabled,
  onSend,
}: {
  control: Control;
  disabled: boolean;
  onSend: (command: string) => void;
}) {
  const options = control.options ?? [];
  const [value, setValue] = useState<string>(options[0]?.command ?? "");
  if (options.length === 0) return null;
  return (
    <Select
      label={control.label}
      value={value}
      disabled={disabled}
      options={options.map((o) => ({ value: o.command, label: o.label }))}
      onChange={(next) => {
        setValue(next);
        onSend(next);
      }}
    />
  );
}

/** Whether the latest status carries at least one of the declared fields. */
function hasAnyField(status: Record<string, string> | null, telemetry: TelemetrySpec): boolean {
  return status != null && telemetry.fields.some((f) => status[f.key] !== undefined);
}

/**
 * Parse the most recent received `STATUS` line into `key → value` pairs. Scans
 * from the newest line back so a burst of updates always shows the latest.
 */
function parseLatestStatus(
  lines: ConsoleLine[],
  telemetry: TelemetrySpec | null,
): Record<string, string> | null {
  if (!telemetry) return null;
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line || line.dir !== "rx") continue;
    const text = line.text.trim();
    if (!text.startsWith(telemetry.match)) continue;
    const body = text.slice(telemetry.match.length).trim();
    const out: Record<string, string> = {};
    for (const token of body.split(/\s+/)) {
      const eq = token.indexOf("=");
      if (eq > 0) out[token.slice(0, eq)] = token.slice(eq + 1);
    }
    return out;
  }
  return null;
}
