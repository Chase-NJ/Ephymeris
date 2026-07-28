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
 *
 * **Nothing here truncates a name.** A control's label is the operator's only
 * description of what it will do to the rig, and a profile is free to declare
 * as many as the hardware has — so labels wrap and the layout gives way, never
 * the other way round. `NodeDetail`'s width toggle then decides how many
 * columns that layout gets.
 */
export function UtilityControls({
  box,
  profile,
  canSend,
  wide,
  onRequestWidth,
}: {
  box: number;
  profile: TaskProfile;
  canSend: boolean;
  /** The panel is at its wide width — worth more grid columns. */
  wide: boolean;
  /** Widen the panel, or null when it already is. */
  onRequestWidth: (() => void) | null;
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

  // How many channels the widest grid carries. A box with eighteen outputs is
  // the case that made the docked width untenable, so the offer to widen is
  // driven by that count rather than shown unconditionally.
  const busiest = Math.max(0, ...grids.map((c) => c.channels?.length ?? 0));

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
                // A long label wraps inside the button rather than pushing it
                // past the panel edge — the name is the point of the control.
                className="max-w-full text-left whitespace-normal"
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
          wide={wide}
        />
      ))}

      {onRequestWidth && busiest > 6 && (
        <button
          type="button"
          onClick={onRequestWidth}
          className="mt-1.5 text-left text-[10px] text-static underline decoration-halo underline-offset-2 hover:text-starlight"
        >
          {busiest} channels — widen the panel for more room
        </button>
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

/**
 * A `grid` control: one cell per piece of hardware, each with a live state lamp
 * and its own toggle/pulse.
 *
 * A box has 18 controllable outputs; as flat buttons that would be 36 controls
 * in a wrapped row with no indication of which are open. The grid exists so a
 * lab tech priming a line can see, at a glance, exactly what is energized —
 * which for solenoids on a fluid rig is a safety readout, not a convenience.
 *
 * **The label gets its own line, above the buttons.** Sharing a row with them
 * left it whatever width was left over, which at the docked panel width was
 * about eight characters — so `Left water solenoid` and `Left odor valve`
 * rendered as the same ellipsis, on a control that opens a fluid line. Stacking
 * costs vertical space in a panel that already scrolls, and buys a name that is
 * correct at every width. The label wraps rather than truncating for the same
 * reason.
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
  wide,
}: {
  control: Control;
  status: Record<string, string> | null;
  disabled: boolean;
  onSend: (command: string) => void;
  wide: boolean;
}) {
  const channels = control.channels ?? [];
  if (channels.length === 0) return null;

  return (
    <div className="mt-2">
      <div className="mb-1 text-[11px] text-static">{control.label}</div>
      {/* Column count follows the panel's own width, not the viewport's — a
          `sm:` breakpoint would key an 820px panel's layout to the size of the
          monitor it happens to be on. */}
      <div className={`grid gap-1 ${wide ? "grid-cols-3" : "grid-cols-2"}`}>
        {channels.map((ch) => {
          const raw = ch.state ? status?.[ch.state] : undefined;
          const known = raw !== undefined;
          const on = known && (raw === "1" || raw === "open" || raw === "true");
          return (
            <div
              key={ch.label}
              className="flex flex-col gap-1 rounded-sm border border-halo px-2 py-1.5"
            >
              <span className="flex items-start gap-1.5">
                <motion.span
                  className="mt-[5px] size-1.5 shrink-0 rounded-full"
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
                  className={`min-w-0 font-mono text-[11px] leading-snug break-words ${
                    on ? "text-starlight" : "text-static"
                  }`}
                >
                  {ch.label}
                </span>
              </span>
              {(ch.toggle || ch.pulse) && (
                <span className="flex flex-wrap items-center gap-1">
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
                </span>
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
      // A long option name sizes the select; capping it at the row keeps that
      // from pushing the whole strip past the panel edge.
      className="max-w-full"
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
