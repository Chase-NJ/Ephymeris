import { motion } from "framer-motion";

import { springSnappy } from "@/lib/motion";
import type { PortStateName } from "@/lib/hardware/store";

/**
 * Per-box state badge (`ARCHITECTURE.md#states`).
 *
 * Driven by two independent inputs: the port's own state-machine state and the
 * out-of-band presence check (`ARCHITECTURE.md#board-discovery`) — hence
 * `detected` arriving separately, so the same badge can express "connected,
 * idle" vs "not detected". Colours are the theme's semantic set: Ion strictly
 * for connected/nominal, matte amber for transitional work, matte red for
 * faults. Transitions animate rather than snap, to reinforce that a port is
 * mid-operation.
 */

const META: Record<PortStateName, { label: string; color: string; busy?: boolean }> = {
  IDLE: { label: "idle", color: "var(--color-static)" },
  PASSTHROUGH: { label: "passthrough", color: "var(--color-status-ok)" },
  FLASHING: { label: "flashing", color: "var(--color-status-warning)", busy: true },
  RESETTING: { label: "resetting", color: "var(--color-status-warning)", busy: true },
  IN_SESSION: { label: "in session", color: "var(--color-pulsar)" },
  ERROR: { label: "error", color: "var(--color-status-error)" },
};

export function StateBadge({
  state,
  detected,
}: {
  state: PortStateName;
  detected: boolean;
}) {
  // A box whose board isn't present and isn't mid-anything reads as absent,
  // not "idle" — presence and port state are separate facts
  // (`ARCHITECTURE.md#board-discovery`).
  const absent = !detected && state === "IDLE";
  const meta = META[state];
  const color = absent ? "var(--color-halo)" : meta.color;
  const label = absent ? "not detected" : meta.label;

  return (
    <span className="flex shrink-0 items-center gap-1.5 rounded-sm border border-halo bg-void/50 px-2 py-[3px] font-mono text-[10px] text-static">
      <motion.span
        className="size-1.5 rounded-full"
        animate={{
          backgroundColor: color,
          // The "spinner": busy states pulse rather than sit solid.
          opacity: meta.busy ? [1, 0.25, 1] : 1,
        }}
        transition={
          meta.busy
            ? { opacity: { repeat: Infinity, duration: 0.9 }, backgroundColor: springSnappy }
            : springSnappy
        }
      />
      {label}
    </span>
  );
}
