import { motion } from "framer-motion";

import { springSnappy } from "@/lib/motion";
import type { ConnectionStatus } from "@/lib/ws/client";

/**
 * Sidecar connection readout.
 *
 * Uses the semantic status colours from `ARCHITECTURE.md#theme`, which are
 * reserved for state and never used decoratively. `Ion` in particular is spent
 * only on "connected / nominal".
 */

const LABEL: Record<ConnectionStatus, string> = {
  starting: "starting",
  connecting: "connecting",
  connected: "connected",
  reconnecting: "reconnecting",
  down: "sidecar down",
};

const COLOR: Record<ConnectionStatus, string> = {
  starting: "var(--color-static)",
  connecting: "var(--color-static)",
  connected: "var(--color-status-ok)",
  reconnecting: "var(--color-status-warning)",
  down: "var(--color-status-error)",
};

export function SidecarStatusPill({ status }: { status: ConnectionStatus }) {
  return (
    <span className="flex items-center gap-2 rounded-sm border border-halo bg-nebula px-2.5 py-1 font-mono text-[11px] text-static">
      <motion.span
        className="inline-block size-1.5 rounded-full"
        animate={{ backgroundColor: COLOR[status] }}
        transition={springSnappy}
      />
      {LABEL[status]}
    </span>
  );
}
