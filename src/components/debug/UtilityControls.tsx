import { motion } from "framer-motion";
import { Power, Zap } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { useBoxOutput } from "@/lib/hardware/context";
import { KIND_COLOR } from "@/lib/hardware/types";
import { springSnappy } from "@/lib/motion";
import type { Control, ControlChannel, TaskProfile, TelemetrySpec } from "@/lib/sessions/types";
import type { ConsoleLine } from "@/lib/hardware/store";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

import { PrimeControls } from "./PrimeControls";

/**
 * Debug-Mode controls + live status for a **utility** sketch
 * (`TASKS.md#utility-controls-and-telemetry`). Driven entirely by the sketch's
 * Task Profile:
 *
 *  - `controls` render as buttons / selects / channel grids; each sends its
 *    serial command over the existing `port.send` primitive (no new wire
 *    command). Enabled only in `PASSTHROUGH`, matching the console's send gate.
 *  - `telemetry` parses the sketch's non-persisted `STATUS` lines out of
 *    `port.output` into a labelled strip. Nothing here is stored — it's live
 *    display only (`ARCHITECTURE.md#invariants`).
 *  - **Prime** (`PrimeControls`) is the one composed control: it is built from
 *    the fluid grid's own `pulse` commands and the profile's pulse-width verb,
 *    and is offered whenever a grid of fluid lines is declared.
 *
 * **Colour is the channel's family.** A fluid line is drawn in the reward
 * colour, an odor line in the emitter colour, the vacuum and the light in
 * theirs — `KIND_COLOR`, the same six the board map and every trial table use.
 * The lamp lights in that colour, the switch fills with it, and the group
 * header carries it, so "which of these is a water line" is answered by the
 * colour before the label is read. Status colour stays state-only.
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

  const isOpen = (key: string | undefined) => {
    const raw = key ? status?.[key] : undefined;
    return raw === "1" || raw === "open" || raw === "true";
  };

  // Grids own their own block; buttons and selects share one inline row.
  const inline = controls.filter((c) => c.type !== "grid");
  const grids = controls.filter((c) => c.type === "grid");

  // The fluid grid, for Prime: by id first, then by the shape of its state
  // keys. A profile that declares neither simply has nothing to prime.
  const fluids =
    grids.find((g) => g.id === "fluids") ??
    grids.find((g) => (g.channels ?? []).some((ch) => familyOf(ch) === "reward"));

  // How many channels the widest grid carries. A box with eighteen outputs is
  // the case that made the docked width untenable, so the offer to widen is
  // driven by that count rather than shown unconditionally.
  const busiest = Math.max(0, ...grids.map((c) => c.channels?.length ?? 0));

  const pulseMs = status?.["pulse"] !== undefined ? Number(status["pulse"]) : null;

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
                // "All off" is the one control that must read as the safe way
                // out, so it is the one that carries a border and an icon.
                variant={isAllOff(c) ? "outline" : "secondary"}
                onClick={() => c.command && send(c.command)}
                disabled={!canSend || !c.command}
                title={canSend ? (c.command ?? c.label) : "Open passthrough to control"}
                // A long label wraps inside the button rather than pushing it
                // past the panel edge — the name is the point of the control.
                className="max-w-full text-left whitespace-normal"
              >
                {isAllOff(c) && <Power size={12} strokeWidth={2} />}
                {c.label}
              </Button>
            ),
          )}
        </div>
      )}

      {fluids && (
        <PrimeControls
          channels={fluids.channels ?? []}
          canSend={canSend}
          currentPulseMs={pulseMs !== null && Number.isFinite(pulseMs) ? pulseMs : null}
          isOpen={isOpen}
          onSend={send}
        />
      )}

      {grids.map((c) => (
        <ChannelGrid
          key={c.id}
          control={c}
          isOpen={isOpen}
          known={(key) => key !== undefined && status?.[key] !== undefined}
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
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-halo pt-2">
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
 * A `grid` control: one row per piece of hardware, each with a live lamp, a
 * switch that latches it, and a pulse.
 *
 * A box has 18 controllable outputs; as flat buttons that would be 36 controls
 * in a wrapped row with no indication of which are open. The grid exists so a
 * lab tech priming a line can see, at a glance, exactly what is energized —
 * which for solenoids on a fluid rig is a safety readout, not a convenience.
 *
 * **The switch IS the state.** It used to be an "Open"/"Close" button whose
 * word flipped with the lamp, which is two things saying one fact and a verb
 * that reads as an instruction rather than a position. A switch shows where
 * the valve is and is the thing you move to change it — and it fills with the
 * channel's family colour, so an open water line and an open odor line are
 * told apart across the room.
 *
 * The lamp reads the channel's `state` telemetry key: "1"/"open"/"true" is
 * energized, anything else is closed, and an absent key means the sketch
 * doesn't report that channel — the lamp stays neutral and the switch stays
 * at "off" without claiming it, because not-reported and closed are different
 * facts.
 */
function ChannelGrid({
  control,
  isOpen,
  known,
  disabled,
  onSend,
  wide,
}: {
  control: Control;
  isOpen: (key: string | undefined) => boolean;
  known: (key: string | undefined) => boolean;
  disabled: boolean;
  onSend: (command: string) => void;
  wide: boolean;
}) {
  const channels = control.channels ?? [];
  const first = channels[0];
  if (!first) return null;

  const family = familyOf(first);
  const colour = family ? (KIND_COLOR[family] ?? "var(--color-static)") : "var(--color-static)";
  const openCount = channels.filter((ch) => isOpen(ch.state)).length;

  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span aria-hidden className="size-1.5 rounded-full" style={{ background: colour }} />
        <span className="text-[11px] font-medium text-starlight">{control.label}</span>
        <span className="font-mono text-[10px] text-static/70">
          {openCount > 0 ? (
            <span style={{ color: colour }}>{openCount} open</span>
          ) : (
            "all closed"
          )}
        </span>
      </div>
      {/* Column count follows the panel's own width, not the viewport's — a
          `sm:` breakpoint would key an 820px panel's layout to the size of the
          monitor it happens to be on. */}
      <div className={`grid gap-1 ${wide ? "grid-cols-3" : "grid-cols-2"}`}>
        {channels.map((ch) => {
          const on = isOpen(ch.state);
          const reported = known(ch.state);
          const own = KIND_COLOR[familyOf(ch) ?? ""] ?? colour;
          return (
            <div
              key={ch.label}
              className="flex items-center gap-2 rounded-sm border px-2 py-1.5 transition-colors"
              style={{
                borderColor: on ? own : "var(--color-halo)",
                background: on ? `color-mix(in srgb, ${own} 9%, transparent)` : undefined,
              }}
            >
              <motion.span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                animate={{
                  backgroundColor: !reported ? "var(--color-halo)" : on ? own : "var(--color-static)",
                  opacity: reported && !on ? 0.4 : 1,
                  scale: on ? 1.25 : 1,
                }}
                transition={springSnappy}
              />
              <span
                className={`min-w-0 flex-1 font-mono text-[11px] leading-snug break-words ${
                  on ? "text-starlight" : "text-static"
                }`}
              >
                {ch.label}
              </span>
              {ch.pulse && (
                <button
                  type="button"
                  onClick={() => onSend(ch.pulse!)}
                  disabled={disabled}
                  title={disabled ? "Open passthrough to control" : `${ch.pulse} — open for the pulse width, then close`}
                  aria-label={`Pulse ${ch.label}`}
                  className="shrink-0 rounded-sm p-1 text-static transition-colors hover:text-starlight disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Zap size={13} strokeWidth={1.75} />
                </button>
              )}
              {ch.toggle && (
                <ChannelSwitch
                  on={on}
                  colour={own}
                  disabled={disabled}
                  label={`${on ? "Close" : "Open"} ${ch.label}`}
                  title={disabled ? "Open passthrough to control" : ch.toggle}
                  onChange={() => onSend(ch.toggle!)}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The switch. `controls.Toggle`'s geometry with the fill in the channel's own
 * colour rather than Pulsar — Pulsar is the accent for the app's controls, and
 * a valve is not an app control, it is a piece of the rig.
 *
 * It sends `TOGGLE` and lets the board's telemetry move the knob: a switch that
 * flipped on the click and then flipped back when the board disagreed would be
 * the app claiming a valve state it does not know. So the knob follows `on`,
 * which follows the sketch's `STATUS`.
 */
export function ChannelSwitch({
  on,
  colour,
  disabled,
  label,
  title,
  onChange,
}: {
  on: boolean;
  colour: string;
  disabled: boolean;
  label: string;
  title: string;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onChange}
      className="flex h-[20px] w-[34px] shrink-0 items-center rounded-xl p-[3px] transition-colors disabled:cursor-not-allowed disabled:opacity-40"
      style={{ background: on ? colour : "var(--color-halo)" }}
    >
      <motion.span
        layout
        transition={springSnappy}
        className="block size-[14px] rounded-xl bg-starlight"
        style={{ marginLeft: on ? "auto" : 0 }}
      />
    </button>
  );
}

/** A `select` control: choosing an option sends that option's command. */
export function SelectControl({
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

/**
 * Which channel family a grid row belongs to, from its telemetry key.
 *
 * The utility sketch's keys are `f1..f4`, `o1..o12`, `vac`, `light`; the
 * families are the rig's channel kinds (`KIND_COLOR`), so a fluid line here
 * wears the same colour it wears on the board map. Read from the key rather
 * than from a declared kind because a `ControlChannel` declares none — and
 * adding one would change `profile_hash` for every utility profile.
 */
/**
 * What a row drives. A generated profile says so outright (`kind`, from the
 * Rig page — `TASKS.md#the-box-utility`); the key-shape guess is for a
 * hand-written profile that predates it.
 */
export function familyOf(ch: ControlChannel): keyof typeof KIND_COLOR | undefined {
  if (ch.kind && ch.kind in KIND_COLOR) return ch.kind as keyof typeof KIND_COLOR;
  const key = ch.state?.toLowerCase() ?? "";
  if (/^f\d+$/.test(key)) return "reward";
  if (/^o\d+$/.test(key)) return "emitter";
  if (key === "vac") return "vacuum";
  if (key === "light") return "cue";
  return undefined;
}

export function isAllOff(c: Control): boolean {
  return c.id === "alloff" || /^ALLOFF$/i.test(c.command ?? "");
}

/** Whether the latest status carries at least one of the declared fields. */
function hasAnyField(status: Record<string, string> | null, telemetry: TelemetrySpec): boolean {
  return status != null && telemetry.fields.some((f) => status[f.key] !== undefined);
}

/**
 * Parse the most recent received `STATUS` line into `key → value` pairs. Scans
 * from the newest line back so a burst of updates always shows the latest.
 */
export function parseLatestStatus(
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
