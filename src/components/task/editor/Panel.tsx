import { motion } from "framer-motion";
import type { ReactNode } from "react";

import { PanelTitle } from "@/components/charts/PanelTitle";

/**
 * One of the editor's telemetry panels (`ARCHITECTURE.md#telemetry-panels`):
 * the subject in mono capitals, a note beside it, an optional control at the
 * right, then the body. A `layoutId` lets the page move it between its split
 * and stacked homes on a spring rather than jumping.
 */
export function Panel({
  id,
  name,
  note,
  right,
  className = "",
  bodyClassName = "",
  lit = false,
  onPointerEnter,
  onPointerLeave,
  children,
}: {
  id: string;
  name: string;
  note?: ReactNode;
  right?: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Lit from the machine (a chip hover) — the border takes Pulsar; no glow. */
  lit?: boolean;
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
  children: ReactNode;
}) {
  return (
    <motion.section
      layoutId={`editor-${id}`}
      layout="position"
      className={`telemetry flex min-h-0 flex-col transition-[border-color] ${
        lit ? "!border-pulsar/70" : ""
      } ${className}`}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      <header className="flex shrink-0 items-center gap-3 px-4 pt-3 pb-2">
        <span className="min-w-0 flex-1">
          <PanelTitle name={name} note={note} />
        </span>
        {right}
      </header>
      <div className={`flex min-h-0 flex-1 flex-col px-4 pb-3 ${bodyClassName}`}>{children}</div>
    </motion.section>
  );
}
