import { diagnosticsOn, meterOf } from "@/lib/taskdef/spine";
import type { SpineRam, TaskDiagnostic } from "@/lib/ws/protocol";

import { ProblemLines } from "./bits";

/** Each part a step lighter: one hue, Pulsar, flat — no gradient (`ARCHITECTURE.md#theme`). */
const SHADES = [1, 0.78, 0.6, 0.45, 0.33, 0.24];

/**
 * The parameter-RAM meter (`TASKS.md#the-spine-editor`): what the task's data
 * takes of the board's RAM, out of the 5000 B budget, by part.
 *
 * Every number is the sidecar's (`SpineView.ram`, `spine.ram_parts`): this
 * draws them. OVER BUDGET IS A DIAGNOSTIC, NEVER A REFUSAL. The bar stretches
 * past the budget's mark with the overflow in the error colour, the SPN105
 * the sidecar placed on `ram` is said under it, and nothing in the editor is
 * disabled: the task still saves, and its folder carries the `#error` that
 * stops it compiling.
 */
export function RamMeter({ ram, diagnostics }: { ram: SpineRam | null; diagnostics: readonly TaskDiagnostic[] }) {
  const meter = ram ? meterOf(ram) : null;
  const problems = diagnosticsOn(diagnostics, "ram");
  if (!ram) return <p className="text-[11px] text-static">Measuring…</p>;
  if (!meter) {
    return (
      <p className="text-[11px] leading-relaxed text-static">
        Nothing to measure: this spine cannot be written as a table yet. The problems on its phases
        say why.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="font-mono text-[12px] text-starlight">
        <span className={meter.over ? "text-status-error" : ""}>{meter.bytes.toLocaleString()} B</span>
        <span className="text-static"> of {meter.budget.toLocaleString()} B</span>
      </p>
      <div className="relative h-3 w-full overflow-hidden rounded-[2px] bg-void/60" role="img" aria-label={`${meter.bytes} of ${meter.budget} bytes`}>
        {meter.segments.map((s, i) => (
          <span
            key={s.label}
            className="absolute inset-y-0 bg-pulsar"
            style={{ left: `${s.start * 100}%`, width: `${s.width * 100}%`, opacity: SHADES[i % SHADES.length] }}
            title={`${s.label}: ${s.bytes} B`}
          />
        ))}
        {meter.over && (
          <span
            className="absolute inset-y-0"
            style={{ left: `${meter.budgetAt * 100}%`, right: 0, background: "var(--color-status-error)", opacity: 0.85 }}
          />
        )}
        <span aria-hidden className="absolute inset-y-0 w-px bg-starlight" style={{ left: `calc(${meter.budgetAt * 100}% - 1px)` }} />
      </div>
      <ul className="flex flex-col gap-0.5">
        {meter.segments.map((s, i) => (
          <li key={s.label} className="flex items-center gap-1.5 text-[11px] text-static">
            <span aria-hidden className="size-2 rounded-[1px] bg-pulsar" style={{ opacity: SHADES[i % SHADES.length] }} />
            <span className="flex-1">{s.label}</span>
            <span className="font-mono text-starlight/90">{s.bytes} B</span>
          </li>
        ))}
      </ul>
      <ProblemLines diagnostics={problems} />
    </div>
  );
}
