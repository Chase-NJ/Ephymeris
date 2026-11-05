import { ArrowUpRight, Plus, TriangleAlert, X } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { NumberInput } from "@/components/common/controls";
import type { SpineDefinition } from "@/lib/taskdef/spine";
import type { ProblemLine } from "@/lib/taskdef/spineProblems";
import type { ChannelGroup } from "@/lib/taskdef/spineWords";
import type { SpineStoredValue, TaskDiagnostic, TaskTarget } from "@/lib/ws/protocol";

/**
 * Small pieces the spine editor's panels share: a problem said where it is as
 * an instruction with its fix, a value stored over the spine's, an optional
 * number, a set of slots, a channel picker grouped by kind.
 */

const LINKS: Record<NonNullable<ProblemLine["link"]>, { to: string; label: string }> = {
  wiring: { to: "/config/wiring", label: "Open the Rig page" },
  strobes: { to: "/task/strobes", label: "Open the strobe vocabulary" },
};

/**
 * Problems as instructions (`spineProblems.problemLines`): the error colour,
 * the code, what to do, then the one-click fix or the page that answers it.
 * The sidecar's own words are the hover.
 */
export function ProblemLines({
  lines,
  onFix,
  className = "",
}: {
  lines: readonly ProblemLine[];
  /** Applies a fix to the document. */
  onFix: (apply: (def: SpineDefinition) => SpineDefinition) => void;
  className?: string;
}) {
  const navigate = useNavigate();
  if (lines.length === 0) return null;
  return (
    <ul className={`flex flex-col gap-0.5 ${className}`}>
      {lines.map((line, i) => {
        const link = line.link ? LINKS[line.link] : null;
        return (
          <li
            key={`${line.code}-${i}`}
            className="flex flex-wrap items-start gap-x-1.5 gap-y-0.5 text-[11px] leading-snug text-status-error"
            title={line.detail.join("\n")}
          >
            <TriangleAlert size={11} strokeWidth={1.75} className="mt-0.5 shrink-0" />
            <span>
              <span className="font-mono text-[10px]">{line.code}</span> {line.instruction}
            </span>
            {line.fix && (
              <button
                type="button"
                onClick={() => onFix(line.fix!.apply)}
                className="rounded-sm border border-pulsar/60 px-1.5 text-[10px] text-pulsar transition-colors hover:border-pulsar hover:text-starlight"
              >
                {line.fix.label}
              </button>
            )}
            {link && (
              <button
                type="button"
                onClick={() => navigate(link.to)}
                className="flex items-center gap-0.5 text-[10px] text-pulsar transition-colors hover:text-starlight"
              >
                {link.label}
                <ArrowUpRight size={10} strokeWidth={1.75} />
              </button>
            )}
          </li>
        );
      })}
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

/** A quiet line of explanation under a heading or beside a control. */
export function Note({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={`text-[10px] leading-relaxed text-static/80 ${className}`}>{children}</p>;
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
        aria-label={`Add ${label}`}
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
      {all.length === 0 && <span className="text-[11px] text-static/70">no roles of this kind</span>}
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

/**
 * A channel picker: the channels the preview offers a slot
 * (`SpineSlotView.channels`), each by its Rig-tab label and grouped by kind
 * (`spineWords.channelGroups`). A bound name the preview no longer offers
 * stays listed under its own name, so it can be seen and changed.
 */
export function ChannelSelect({
  value,
  groups,
  label,
  tone = "normal",
  className = "",
  onChange,
}: {
  value: string;
  groups: readonly ChannelGroup[];
  label: string;
  tone?: "normal" | "error";
  className?: string;
  onChange: (name: string) => void;
}) {
  const offered = groups.some((g) => g.choices.some((c) => c.name === value));
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={tone === "error" ? { color: "var(--color-status-error)" } : undefined}
      className={`rounded-sm border border-halo bg-nebula px-2.5 py-1.5 text-[12px] ${tone === "normal" ? "text-starlight" : ""} ${className}`}
    >
      <option value="">—</option>
      {value && !offered && <option value={value}>{value} (not on this rig)</option>}
      {groups.map((group) => (
        <optgroup key={group.kind || "other"} label={group.label}>
          {group.choices.map((c) => (
            <option key={c.name} value={c.name}>
              {c.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
