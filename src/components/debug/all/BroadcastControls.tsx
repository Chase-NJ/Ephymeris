import { motion } from "framer-motion";
import { Power, Zap } from "lucide-react";

import { Button } from "@/components/common/controls";
import { KIND_COLOR } from "@/lib/hardware/types";
import { springSnappy } from "@/lib/motion";
import type { Control, TaskProfile } from "@/lib/sessions/types";

import { PrimeControls } from "../PrimeControls";
import { ChannelSwitch, SelectControl, familyOf, isAllOff } from "../UtilityControls";

/**
 * The utility sketch's controls, sent to every controllable box at once
 * (`USER-GUIDE.md#commanding-every-box`).
 *
 * Built from the same profile `UtilityControls` reads — every box carries the
 * one utility sketch the rig generated, so its controls mean the same thing
 * on each. What changes is the lamp: one per box, so "is line 3 open" is
 * answered across the whole rig at once, and the switch is set ON or OFF
 * outright (never `TOGGLE`, which would flip boxes that disagree in opposite
 * directions). Every command still goes over `port.send`, one per box.
 */
export function BroadcastControls({
  profile,
  boxes,
  statuses,
  onSend,
}: {
  profile: TaskProfile;
  /** The boxes commands reach: targeted, console open, on the utility sketch. */
  boxes: readonly number[];
  /** Each box's latest parsed `STATUS`, or null before the first. */
  statuses: ReadonlyMap<number, Record<string, string> | null>;
  onSend: (command: string) => void;
}) {
  const controls = profile.controls ?? [];
  const inline = controls.filter((c) => c.type !== "grid");
  const grids = controls.filter((c) => c.type === "grid");
  const canSend = boxes.length > 0;

  const openOn = (box: number, key: string | undefined) => {
    const raw = key ? statuses.get(box)?.[key] : undefined;
    return raw === "1" || raw === "open" || raw === "true";
  };
  const reported = (box: number, key: string | undefined) =>
    key !== undefined && statuses.get(box)?.[key] !== undefined;

  const fluids =
    grids.find((g) => g.id === "fluids") ??
    grids.find((g) => (g.channels ?? []).some((ch) => familyOf(ch) === "reward"));
  const firstPulse = boxes.map((b) => statuses.get(b)?.["pulse"]).find((v) => v !== undefined);
  const pulseMs = firstPulse !== undefined && Number.isFinite(Number(firstPulse)) ? Number(firstPulse) : null;

  return (
    <div className="flex flex-col gap-1">
      {inline.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {inline.map((c) =>
            c.type === "select" ? (
              <SelectControl key={c.id} control={c} disabled={!canSend} onSend={onSend} />
            ) : (
              <Button
                key={c.id}
                variant={isAllOff(c) ? "outline" : "secondary"}
                onClick={() => c.command && onSend(c.command)}
                disabled={!canSend || !c.command}
                title={canSend ? `${c.command ?? c.label} → ${boxes.length} box${boxes.length === 1 ? "" : "es"}` : "Open the consoles to control"}
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
          currentPulseMs={pulseMs}
          // A line reads open when it is open on any box — Prime only uses this
          // to show what is flowing, and "somewhere" is the honest answer.
          isOpen={(key) => boxes.some((b) => openOn(b, key))}
          onSend={onSend}
        />
      )}

      {grids.map((grid) => (
        <BroadcastGrid
          key={grid.id}
          control={grid}
          boxes={boxes}
          openOn={openOn}
          reported={reported}
          disabled={!canSend}
          onSend={onSend}
        />
      ))}
    </div>
  );
}

/**
 * One grid, across the rig: a row per channel, a lamp per box in that row, a
 * pulse, and a switch that reads ON only when the channel is open on every
 * box. Clicking it sets every box the same way — ON, or OFF once all are on.
 */
function BroadcastGrid({
  control,
  boxes,
  openOn,
  reported,
  disabled,
  onSend,
}: {
  control: Control;
  boxes: readonly number[];
  openOn: (box: number, key: string | undefined) => boolean;
  reported: (box: number, key: string | undefined) => boolean;
  disabled: boolean;
  onSend: (command: string) => void;
}) {
  const channels = control.channels ?? [];
  const first = channels[0];
  if (!first) return null;
  const family = familyOf(first);
  const colour = family ? (KIND_COLOR[family] ?? "var(--color-static)") : "var(--color-static)";

  return (
    <div className="mt-2.5">
      <div className="mb-1 flex items-center gap-2">
        <span aria-hidden className="size-1.5 rounded-full" style={{ background: colour }} />
        <span className="text-[11px] font-medium text-starlight">{control.label}</span>
        <span className="font-mono text-[10px] text-static/70">lamps: one per box</span>
      </div>
      <div className="grid grid-cols-2 gap-1">
        {channels.map((ch) => {
          const own = KIND_COLOR[familyOf(ch) ?? ""] ?? colour;
          const openCount = boxes.filter((b) => openOn(b, ch.state)).length;
          const allOn = boxes.length > 0 && openCount === boxes.length;
          const name = ch.toggle?.replace(/^TOGGLE\s+/i, "") ?? null;
          return (
            <div
              key={ch.label}
              className="flex items-center gap-2 rounded-sm border px-2 py-1 transition-colors"
              style={{
                borderColor: openCount > 0 ? own : "var(--color-halo)",
                background: openCount > 0 ? `color-mix(in srgb, ${own} 7%, transparent)` : undefined,
              }}
            >
              <span className="min-w-0 flex-1 font-mono text-[11px] leading-snug break-words text-static">
                {ch.label}
                <span className="mt-0.5 flex flex-wrap gap-[3px]" aria-label={`${openCount} of ${boxes.length} open`}>
                  {boxes.map((b) => (
                    <motion.span
                      key={b}
                      title={`Box ${b}: ${!reported(b, ch.state) ? "not reported" : openOn(b, ch.state) ? "open" : "closed"}`}
                      className="size-[6px] rounded-full"
                      animate={{
                        backgroundColor: !reported(b, ch.state)
                          ? "var(--color-halo)"
                          : openOn(b, ch.state)
                            ? own
                            : "var(--color-static)",
                        opacity: reported(b, ch.state) && !openOn(b, ch.state) ? 0.35 : 1,
                        scale: openOn(b, ch.state) ? 1.2 : 1,
                      }}
                      transition={springSnappy}
                    />
                  ))}
                </span>
              </span>
              {ch.pulse && (
                <button
                  type="button"
                  onClick={() => onSend(ch.pulse!)}
                  disabled={disabled}
                  title={disabled ? "Open the consoles to control" : `${ch.pulse} on every box`}
                  aria-label={`Pulse ${ch.label} on every box`}
                  className="shrink-0 rounded-sm p-1 text-static transition-colors hover:text-starlight disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Zap size={13} strokeWidth={1.75} />
                </button>
              )}
              {name && (
                <ChannelSwitch
                  on={allOn}
                  colour={own}
                  disabled={disabled}
                  label={`${allOn ? "Close" : "Open"} ${ch.label} on every box`}
                  title={disabled ? "Open the consoles to control" : `${allOn ? "OFF" : "ON"} ${name} on every box`}
                  onChange={() => onSend(`${allOn ? "OFF" : "ON"} ${name}`)}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
