import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { meterOf, type SpineDefinition } from "@/lib/taskdef/spine";
import type { ProblemLine } from "@/lib/taskdef/spineProblems";
import type { SpineRam } from "@/lib/ws/protocol";

import { ProblemLines } from "./bits";

/** Each part a step lighter: one hue, Pulsar, flat — no gradient (`ARCHITECTURE.md#theme`). */
const SHADES = [1, 0.78, 0.6, 0.45, 0.33, 0.24];

/**
 * The parameter-RAM meter (`TASKS.md#the-spine-editor`): one line under the
 * trial, what the task's data takes of the board's RAM out of the 5000 B
 * budget, with the parts on a disclosure.
 *
 * Every number is the sidecar's (`SpineView.ram`, `spine.ram_parts`): this
 * draws them. OVER BUDGET IS A DIAGNOSTIC, NEVER A REFUSAL. The bar stretches
 * past the budget's mark with the overflow in the error colour, the SPN105
 * the sidecar placed on `ram` is said under it, and nothing in the editor is
 * disabled: the task still saves, and its folder carries the `#error` that
 * stops it compiling.
 */
export function RamMeter({
  ram,
  lines,
  onFix,
}: {
  ram: SpineRam | null;
  /** The problems the sidecar placed on `ram`, as instructions. */
  lines: readonly ProblemLine[];
  onFix: (apply: (def: SpineDefinition) => SpineDefinition) => void;
}) {
  const [open, setOpen] = useState(false);
  const meter = ram ? meterOf(ram) : null;
  const summary = !ram ? "measuring…" : !meter ? "nothing to measure yet" : `${meter.bytes.toLocaleString()} B of ${meter.budget.toLocaleString()} B`;
  return (
    <div className="flex flex-col gap-1.5 border-t border-halo/60 pt-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex flex-wrap items-center gap-2 self-start text-[11px] text-static transition-colors hover:text-starlight"
      >
        {open ? <ChevronDown size={11} strokeWidth={1.75} /> : <ChevronRight size={11} strokeWidth={1.75} />}
        <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">RAM</span>
        <span className={`font-mono ${meter?.over ? "text-status-error" : "text-starlight/90"}`}>{summary}</span>
        {meter && (
          <span className="relative h-1.5 w-[160px] overflow-hidden rounded-[2px] bg-void/60" role="img" aria-label={`${meter.bytes} of ${meter.budget} bytes`}>
            {meter.segments.map((s, i) => (
              <span key={s.label} className="absolute inset-y-0 bg-pulsar" style={{ left: `${s.start * 100}%`, width: `${s.width * 100}%`, opacity: SHADES[i % SHADES.length] }} />
            ))}
            {meter.over && <span className="absolute inset-y-0" style={{ left: `${meter.budgetAt * 100}%`, right: 0, background: "var(--color-status-error)", opacity: 0.85 }} />}
          </span>
        )}
        <span className="text-static/60">of the board's budget</span>
      </button>
      {open && meter && (
        <ul className="flex flex-col gap-0.5 pl-4">
          {meter.segments.map((s, i) => (
            <li key={s.label} className="flex items-center gap-1.5 text-[11px] text-static">
              <span aria-hidden className="size-2 rounded-[1px] bg-pulsar" style={{ opacity: SHADES[i % SHADES.length] }} />
              <span className="w-[160px]">{s.label}</span>
              <span className="font-mono text-starlight/90">{s.bytes} B</span>
            </li>
          ))}
        </ul>
      )}
      {open && ram && !meter && (
        <p className="pl-4 text-[11px] leading-relaxed text-static">
          This task cannot be written as a table yet. The problems above the diagram and on its roles, steps, trial types and blocks say why.
        </p>
      )}
      <ProblemLines lines={lines} onFix={onFix} />
    </div>
  );
}
