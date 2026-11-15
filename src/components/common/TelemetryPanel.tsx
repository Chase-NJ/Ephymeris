import type { ReactNode } from "react";

import { PanelTitle } from "@/components/charts/PanelTitle";

/**
 * A telemetry panel (`ARCHITECTURE.md#telemetry-panels`): the subject in mono
 * capitals with a note beside it, an optional control at the right, then the
 * body. The display surface Analytics, Recording, the task editor, the
 * Dashboard and Debug's all-boxes view share — one component, so every panel
 * names itself the same way.
 */
export function TelemetryPanel({
  name,
  note,
  right,
  className = "",
  bodyClassName = "",
  children,
}: {
  name: string;
  note?: ReactNode;
  right?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section className={`telemetry flex min-h-0 flex-col ${className}`}>
      <header className="flex shrink-0 items-center gap-3 px-4 pt-2.5 pb-1.5">
        <span className="min-w-0 flex-1">
          <PanelTitle name={name} note={note} />
        </span>
        {right}
      </header>
      <div className={`flex min-h-0 flex-1 flex-col px-4 pb-3 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
