import { Plus } from "lucide-react";
import { Fragment, useState } from "react";

import type { SpinePhase } from "@/lib/taskdef/spine";
import { diagnosticsOn } from "@/lib/taskdef/spine";
import { PHASE_HELP, PHASE_LABEL } from "@/lib/taskdef/spineLabels";
import { phaseCaption } from "@/lib/taskdef/spineWords";
import type { TaskDiagnostic } from "@/lib/ws/protocol";

import { problemTitle } from "./bits";

/**
 * The trial, drawn left to right in time (`TASKS.md#the-spine-editor`): one
 * node per phase, captioned in words with what it waits for, turns on and
 * how long, and the ITI leading back to the start of the next trial. The
 * first Present carries the "stimulus" mark: it is what decides whether an
 * early end before it is an abort before the stimulus, and after it an abort
 * during sampling or an omission.
 *
 * DRAWN FROM THE PREVIEW. `phases` is the preview's `profile.spine.spine`, the
 * snapshot the sidecar compiled from the current document — the same snapshot
 * Mission Control's live spine reads — never the document being typed. A
 * phase with problems carries a ring in the error colour and their count; the
 * sidecar placed them there (`TaskDiagnostic.target`).
 *
 * A `+` between two phases inserts one from the palette there. Clicking a
 * phase opens its fields below.
 */
export function SpineDiagram({
  phases,
  kinds,
  diagnostics,
  selected,
  stale,
  onSelect,
  onInsert,
}: {
  phases: readonly SpinePhase[];
  /** The palette's phase kinds (`tasks.spinePalette`). */
  kinds: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  selected: number | null;
  /** The newest edit did not preview: this is the last good drawing. */
  stale: boolean;
  onSelect: (index: number) => void;
  onInsert: (at: number, kind: string) => void;
}) {
  const [insertAt, setInsertAt] = useState<number | null>(null);
  const stimulus = phases.findIndex((p) => p.phase === "present");

  const insert = (at: number) => (
    <button
      type="button"
      aria-label={`Insert a step ${at === 0 ? "first" : `after step ${at}`}`}
      onClick={() => setInsertAt(insertAt === at ? null : at)}
      className={`mt-[3px] flex size-[14px] shrink-0 items-center justify-center self-start rounded-full border transition-colors ${
        insertAt === at ? "border-pulsar text-pulsar" : "border-transparent text-static/40 hover:border-halo hover:text-starlight"
      }`}
    >
      <Plus size={9} strokeWidth={2} />
    </button>
  );

  return (
    <div className={`flex flex-col gap-2 transition-opacity ${stale ? "opacity-50" : ""}`}>
      <div className="scrollbar-slim overflow-x-auto pb-1">
        <div className="min-w-max">
        <div className="relative flex items-start px-1 pt-1">
          {phases.map((phase, i) => {
            const problems = diagnosticsOn(diagnostics, "phase", i);
            const on = selected === i;
            return (
              <Fragment key={i}>
                {insert(i)}
                {i > 0 && <span aria-hidden className="mt-[10px] h-px w-3 shrink-0 bg-halo" />}
                <button
                  type="button"
                  onClick={() => onSelect(i)}
                  title={problemTitle(problems)}
                  aria-label={`Step ${i + 1}: ${PHASE_LABEL[phase.phase] ?? phase.phase}${problems.length ? `, ${problems.length} problem${problems.length === 1 ? "" : "s"}` : ""}`}
                  aria-pressed={on}
                  className="group flex w-[124px] shrink-0 flex-col items-center gap-1 rounded-sm px-1 py-0.5 text-center"
                >
                  <span className="relative flex items-center">
                    <span
                      className={`size-[18px] rounded-full border transition-colors ${
                        on ? "border-pulsar bg-pulsar" : "border-starlight/70 bg-nebula group-hover:border-starlight"
                      }`}
                      style={problems.length ? { outline: "1.5px solid var(--color-status-error)", outlineOffset: 3 } : undefined}
                    />
                    {problems.length > 0 && (
                      <span className="absolute -top-2 left-6 font-mono text-[9px] text-status-error">{problems.length}</span>
                    )}
                  </span>
                  <span className={`text-[11px] ${on ? "text-starlight" : "text-static group-hover:text-starlight"}`}>
                    {PHASE_LABEL[phase.phase] ?? phase.phase}
                    {i === stimulus && (
                      <span className="ml-1 font-mono text-[8px] tracking-[0.12em] text-pulsar uppercase" title="The first stimulus: an early end before it is an abort before the stimulus; from here on, during sampling">
                        stimulus
                      </span>
                    )}
                  </span>
                  <span className="line-clamp-2 text-[10px] leading-tight text-static/80">
                    {phaseCaption(phase) || " "}
                  </span>
                </button>
              </Fragment>
            );
          })}
          {insert(phases.length)}
        </div>
        {/* The ITI leads back to the start: the trial loop. */}
        {phases.length > 0 && (
          // From the first node's centre to the last's: the insert button and
          // half a node in from each end.
          <div aria-hidden className="mx-[66px] mt-1 h-2 border-x border-b border-dashed border-halo" />
        )}
        </div>
      </div>

      {insertAt !== null && (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-static">
            <span>{insertAt === 0 ? "Insert first:" : `Insert after step ${insertAt}:`}</span>
            {kinds.map((kind) => (
              <button
                key={kind}
                type="button"
                title={PHASE_HELP[kind]}
                onClick={() => {
                  onInsert(insertAt, kind);
                  setInsertAt(null);
                }}
                className="rounded-sm border border-halo px-1.5 py-0.5 text-starlight transition-colors hover:border-pulsar/70"
              >
                {PHASE_LABEL[kind] ?? kind}
              </button>
            ))}
            <button type="button" onClick={() => setInsertAt(null)} className="text-static hover:text-starlight">
              cancel
            </button>
          </div>
          <p className="text-[10px] leading-relaxed text-static/70">Hover a step kind for what it does. A new step starts with the first input role and a default time; its fields open below.</p>
        </div>
      )}
    </div>
  );
}
