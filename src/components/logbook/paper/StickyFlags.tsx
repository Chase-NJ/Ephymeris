import { useState } from "react";

import { errorMessage } from "@/lib/analytics/commands";
import type { SessionListItem } from "@/lib/analytics/types";
import { shortDate } from "@/lib/logbook/clock";
import type { SessionNote } from "@/lib/logbook/types";

import { scopeLabel, tagOf } from "../tags";

/** Flags shown before the rest fold behind a count. */
const SHOWN = 3;
/** Each note leans a little, and not all the same way. */
const TILT = ["-0.7deg", "0.5deg", "-0.3deg"] as const;

/**
 * The cohort's open carry-forward flags (`DATA.md#carry-forward-flags`), as
 * sticky notes on whichever page is open: what somebody wanted the next
 * person at the rig to know, stuck there until it is dealt with.
 *
 * The same flags show on every session's page, as they did in the panel
 * above the old readout, because a flag is about the cohort's next session,
 * not the one it was written in. Each names where it came from and turns
 * there.
 */
export function StickyFlags({
  flags,
  sessions,
  sessionId,
  names,
  onOpen,
  onResolve,
}: {
  flags: readonly SessionNote[];
  sessions: readonly SessionListItem[];
  /** The page these are stuck to: a flag from this session needs no link. */
  sessionId: string;
  names: Map<string, string>;
  onOpen: (sessionId: string) => void;
  onResolve: (note: SessionNote) => Promise<void>;
}) {
  const [all, setAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (flags.length === 0) return null;
  const byId = new Map(sessions.map((s) => [s.id, s]));
  const shown = all ? flags : flags.slice(0, SHOWN);

  return (
    <section
      aria-label={`${flags.length} open carry-forward note${flags.length === 1 ? "" : "s"}`}
      className="mt-4"
    >
      <ul className="flex flex-wrap items-start gap-3">
        {shown.map((flag, index) => {
          const origin = byId.get(flag.sessionId);
          const here = flag.sessionId === sessionId;
          return (
            <li
              key={flag.id}
              className="sticky w-[calc(50%-0.375rem)] min-w-[190px] px-3 pt-2.5 pb-2 text-[13.5px] leading-snug"
              style={{ rotate: TILT[index % TILT.length] }}
            >
              <p
                className="smallcaps text-[10.5px] text-ink-red"
                title="Carried forward: stays on every page until someone resolves it"
              >
                ⚑ {tagOf(flag.tag).short}
                {flag.scope.kind !== "session" && ` · ${scopeLabel(flag.scope, names)}`}
              </p>
              <p className="mt-0.5 line-clamp-4 whitespace-pre-wrap" data-selectable>
                {flag.body}
              </p>
              <p className="mt-1.5 flex items-baseline justify-between gap-2 text-[12.5px] text-ink-soft">
                {here ? (
                  <span>from this session</span>
                ) : origin ? (
                  <button type="button" className="ink-link" onClick={() => onOpen(origin.id)}>
                    {origin.prefixName}_{origin.sessionNumber}, {shortDate(origin.date)}
                  </button>
                ) : (
                  <span>from an earlier session</span>
                )}
                <button
                  type="button"
                  className="ink-link"
                  onClick={() => {
                    setError(null);
                    onResolve(flag).catch((err: unknown) => setError(errorMessage(err)));
                  }}
                >
                  resolve
                </button>
              </p>
            </li>
          );
        })}
      </ul>
      {flags.length > SHOWN && (
        <button type="button" className="ink-link mt-2 text-[13px]" onClick={() => setAll(!all)}>
          {all ? "show fewer" : `and ${flags.length - SHOWN} more`}
        </button>
      )}
      {error && (
        <p role="alert" className="mt-1 text-[13px] text-ink-red">
          {error}
        </p>
      )}
    </section>
  );
}
