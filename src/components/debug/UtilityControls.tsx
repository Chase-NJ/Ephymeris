import { motion } from "framer-motion";
import { useMemo, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { useBoxOutput } from "@/lib/hardware/context";
import { springSnappy } from "@/lib/motion";
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

  // Grids own their own block; buttons and selects share one inline row.
  const inline = controls.filter((c) => c.type !== "grid");
  const grids = controls.filter((c) => c.type === "grid");

  return (
    <div className="border-t border-halo px-2.5 py-2">
      {inline.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {inline.map((c) =>
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

      {grids.map((c) => (
        <ChannelGrid
          key={c.id}
          control={c}
          status={status}
          disabled={!canSend}
          onSend={send}
        />
      ))}

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

/**
 * A `grid` control: one row per piece of hardware, each with a live state lamp
 * and its own toggle/pulse.
 *
 * A box has 18 controllable outputs; as flat buttons that would be 36 controls
 * in a wrapped row with no indication of which are open. The grid exists so a
 * lab tech priming a line can see, at a glance, exactly what is energized —
 * which for solenoids on a fluid rig is a safety readout, not a convenience.
 *
 * The lamp reads the channel's `state` telemetry key: "1"/"open"/"true" is
 * energized, anything else is closed, and an absent key means the sketch
 * doesn't report that channel — the lamp stays neutral rather than claiming
 * "closed", because not-reported and closed are different facts.
 */
function ChannelGrid({
  control,
  status,
  disabled,
  onSend,
}: {
  control: Control;
  status: Record<string, string> | null;
  disabled: boolean;
  onSend: (command: string) => void;
}) {
  const channels = control.channels ?? [];
  if (channels.length === 0) return null;

  return (
    <div className="mt-2">
      <div className="mb-1 text-[11px] text-static">{control.label}</div>
      <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        {channels.map((ch) => {
          const raw = ch.state ? status?.[ch.state] : undefined;
          const known = raw !== undefined;
          const on = known && (raw === "1" || raw === "open" || raw === "true");
          return (
            <div
              key={ch.label}
              className="flex items-center gap-2 rounded-sm border border-halo px-2 py-1"
            >
              <motion.span
                className="size-1.5 shrink-0 rounded-full"
                animate={{
                  backgroundColor: !known
                    ? "var(--color-halo)"
                    : on
                      ? "var(--color-status-ok)"
                      : "var(--color-static)",
                  opacity: known && !on ? 0.4 : 1,
                }}
                transition={springSnappy}
              />
              <span
                className={`min-w-0 flex-1 truncate font-mono text-[11px] ${
                  on ? "text-starlight" : "text-static"
                }`}
              >
                {ch.label}
              </span>
              {ch.toggle && (
                <Button
                  onClick={() => onSend(ch.toggle!)}
                  disabled={disabled}
                  title={disabled ? "Open passthrough to control" : ch.toggle}
                >
                  {on ? "Close" : "Open"}
                </Button>
              )}
              {ch.pulse && (
                <Button
                  variant="ghost"
                  onClick={() => onSend(ch.pulse!)}
                  disabled={disabled}
                  title={disabled ? "Open passthrough to control" : ch.pulse}
                >
                  Pulse
                </Button>
              )}
            </div>
          );
        })}
      </div>
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
