import { Flag } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/analytics/commands";
import type { SessionListItem } from "@/lib/analytics/types";
import type { SessionNote } from "@/lib/logbook/types";

import { scopeLabel, tagOf } from "./tags";

/**
 * A cohort's open carry-forward flags (`DATA.md#carry-forward-flags`): things
 * someone wanted the next person at the rig to know. Shown in Step 1, on the
 * running session and in the Log, until someone resolves them.
 *
 * `onResolve` decides which session a resolution is recorded against — the
 * running one on Mission Control, none from Step 1 or the Log.
 */
export function CarryForwardPanel({
  flags,
  sessions,
  names,
  onResolve,
  onOpen,
  title = "Carried forward",
}: {
  flags: SessionNote[];
  sessions: SessionListItem[];
  names: Map<string, string>;
  onResolve: (note: SessionNote) => Promise<void>;
  /** Jump to the session the flag was written in, when the host can. */
  onOpen?: ((sessionId: string) => void) | undefined;
  title?: string;
}) {
  const [error, setError] = useState<string | null>(null);
  if (flags.length === 0) return null;
  const byId = new Map(sessions.map((s) => [s.id, s]));

  return (
    <section
      className="hud overflow-hidden rounded-md border-status-warning/40"
      aria-label={`${flags.length} open carry-forward note${flags.length === 1 ? "" : "s"}`}
    >
      <div className="flex items-center gap-2 border-b border-halo px-4 py-2.5">
        <Flag size={14} strokeWidth={1.75} className="text-status-warning" aria-hidden />
        <span className="text-[12px] font-medium text-starlight">{title}</span>
        <span className="ml-auto font-mono text-[11px] text-static">{flags.length} open</span>
      </div>
      <ul className="divide-y divide-halo/70">
        {flags.map((flag) => {
          const origin = byId.get(flag.sessionId);
          const tag = tagOf(flag.tag);
          return (
            <li key={flag.id} className="flex items-start gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-[12px] leading-relaxed whitespace-pre-wrap text-starlight" data-selectable>
                  {flag.body}
                </p>
                <p className="mt-0.5 text-[11px] text-static">
                  {tag.label} · {scopeLabel(flag.scope, names)} ·{" "}
                  {origin ? (
                    onOpen ? (
                      <button
                        type="button"
                        onClick={() => onOpen(origin.id)}
                        className="font-mono underline decoration-halo underline-offset-2 hover:text-starlight"
                      >
                        {origin.prefixName}_{origin.sessionNumber} · {origin.date}
                      </button>
                    ) : (
                      <span className="font-mono">
                        {origin.prefixName}_{origin.sessionNumber} · {origin.date}
                      </span>
                    )
                  ) : (
                    "an earlier session"
                  )}
                </p>
              </div>
              <Button
                variant="secondary"
                onClick={() => {
                  setError(null);
                  onResolve(flag).catch((err: unknown) => setError(errorMessage(err)));
                }}
              >
                Resolve
              </Button>
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="px-4 pb-2.5 text-[11px] text-status-error">
          {error}
        </p>
      )}
    </section>
  );
}
