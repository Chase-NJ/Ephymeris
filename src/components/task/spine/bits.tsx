import { Plus, TriangleAlert, X } from "lucide-react";
import type { ReactNode } from "react";

import { NumberInput } from "@/components/common/controls";
import type { SpineStoredValue, TaskDiagnostic, TaskTarget } from "@/lib/ws/protocol";

/**
 * Small pieces the spine editor's panels share: a problem said where it is, a
 * value stored over the spine's, an optional number, a set of slots.
 */

/** The sidecar's diagnostics, said in place: the error colour, the code, the message. */
export function ProblemLines({ diagnostics, className = "" }: { diagnostics: readonly TaskDiagnostic[]; className?: string }) {
  if (diagnostics.length === 0) return null;
  return (
    <ul className={`flex flex-col gap-0.5 ${className}`}>
      {diagnostics.map((d, i) => (
        <li key={`${d.location}-${i}`} className="flex items-start gap-1.5 text-[11px] leading-snug text-status-error">
          <TriangleAlert size={11} strokeWidth={1.75} className="mt-0.5 shrink-0" />
          <span>
            <span className="font-mono text-[10px]">{d.code}</span> {d.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The `title` a control with problems carries, so hovering it says why. */
export function problemTitle(diagnostics: readonly TaskDiagnostic[]): string | undefined {
  return diagnostics.length ? diagnostics.map((d) => `${d.code} ${d.message}`).join("\n") : undefined;
}

/**
 * Values the definition stores in `params` over what its spine says, for one
 * target (`SpineView.stored`). They win, so they are shown beside the field
 * they shadow, with the way back to the spine's own value.
 */
export function StoredValues({
  stored,
  target,
  onClear,
}: {
  stored: readonly SpineStoredValue[];
  target: TaskTarget;
  onClear: (key: string) => void;
}) {
  const mine = stored.filter((s) => s.target.kind === target.kind && s.target.index === target.index);
  if (mine.length === 0) return null;
  return (
    <ul className="flex flex-col gap-0.5">
      {mine.map((s) => (
        <li key={s.key} className="flex items-center gap-2 text-[11px] text-static">
          <span>
            Stored: <span className="font-mono text-starlight">{s.key}</span> ={" "}
            <span className="font-mono text-starlight">{String(s.value)}</span>, over the value here
          </span>
          <button
            type="button"
            onClick={() => onClear(s.key)}
            className="text-[11px] text-pulsar transition-colors hover:text-starlight"
          >
            Use the value here
          </button>
        </li>
      ))}
    </ul>
  );
}

/** A labelled field: the label above, the control below. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">{label}</span>
      {children}
    </label>
  );
}

/** A number the definition may leave out: `+` adds it at `initial`, `×` removes it. */
export function OptionalNumber({
  value,
  initial,
  label,
  min,
  max,
  invalid,
  title,
  unit,
  onChange,
}: {
  value: number | undefined;
  initial: number;
  label: string;
  min?: number;
  max?: number;
  invalid?: boolean;
  title?: string | undefined;
  unit?: string;
  onChange: (next: number | undefined) => void;
}) {
  if (value === undefined) {
    return (
      <button
        type="button"
        onClick={() => onChange(initial)}
        className="flex h-[30px] items-center gap-1 self-start rounded-sm border border-dashed border-halo px-2 text-[11px] text-static transition-colors hover:border-static/60 hover:text-starlight"
        title={title}
      >
        <Plus size={11} strokeWidth={1.75} /> add
      </button>
    );
  }
  return (
    <span className="flex items-center gap-1">
      <NumberInput
        value={value}
        fallback={initial}
        integer
        {...(min !== undefined ? { min } : {})}
        {...(max !== undefined ? { max } : {})}
        label={label}
        title={title}
        invalid={invalid === true}
        className="w-[96px]"
        onChange={onChange}
      />
      {unit && <span className="text-[10px] text-static">{unit}</span>}
      <button
        type="button"
        aria-label={`Remove ${label}`}
        onClick={() => onChange(undefined)}
        className="text-static transition-colors hover:text-starlight"
      >
        <X size={12} strokeWidth={1.75} />
      </button>
    </span>
  );
}

/** A set of slots, each a toggle: a window's responses, a phase's outputs. */
export function SlotSet({
  options,
  value,
  label,
  invalid,
  title,
  onChange,
}: {
  options: readonly string[];
  value: readonly string[];
  label: string;
  invalid?: boolean;
  title?: string | undefined;
  onChange: (next: string[]) => void;
}) {
  // A stored name no slot has any more stays shown, so it can be taken off.
  const all = [...options, ...value.filter((v) => !options.includes(v))];
  return (
    <span
      role="group"
      aria-label={label}
      title={title}
      className={`flex flex-wrap gap-1 rounded-sm ${invalid ? "outline outline-1 outline-status-error" : ""}`}
    >
      {all.length === 0 && <span className="text-[11px] text-static/70">no slots of this kind</span>}
      {all.map((slot) => {
        const on = value.includes(slot);
        return (
          <button
            key={slot}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((v) => v !== slot) : [...value, slot])}
            className={`rounded-sm border px-1.5 py-0.5 font-mono text-[11px] transition-colors ${
              on ? "border-pulsar/70 bg-pulsar/15 text-starlight" : "border-halo text-static hover:text-starlight"
            } ${options.includes(slot) ? "" : "line-through"}`}
          >
            {slot}
          </button>
        );
      })}
    </span>
  );
}
