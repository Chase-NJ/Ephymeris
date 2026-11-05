import { Trash2 } from "lucide-react";
import { useState } from "react";

import { NumberInput, Select } from "@/components/common/controls";
import { setPhase, type SpineDefinition, type SpinePhase } from "@/lib/taskdef/spine";
import { FIELD_GROUPS, PHASE_HELP, PHASE_LABEL, phaseFields, type PhaseField } from "@/lib/taskdef/spineLabels";
import { targetLines } from "@/lib/taskdef/spineProblems";
import { classNote, classWord, exitNotes } from "@/lib/taskdef/spineWords";
import { diagnosticsAt } from "@/lib/taskdef/types";
import type { SpineStoredValue, TaskDiagnostic } from "@/lib/ws/protocol";

import { Field, Note, OptionalNumber, ProblemLines, SlotSet, StoredValues, problemTitle } from "./bits";

const OUTPUT_TYPES = new Set(["digital_out", "pwm_out", "tone_out"]);

/**
 * One step's fields, under the diagram, in three groups: what it does, what
 * ends it early, and what follows an early end (`spineLabels.FIELD_GROUPS`).
 * The split is what keeps a timeout (the step's own clock) apart from a
 * penalty (what replaces the ITI after that exit), and the second group says
 * what each early end is scored as (`spineWords.exitNotes`).
 *
 * The fields each kind offers are `spineLabels.PHASE_FIELDS`, rendered
 * generically by their control kind, so a new field of the palette is one
 * line there. Slot pickers offer the spine's own roles by direction; whether a
 * choice is right is the sidecar's to say, and its diagnostics land on the
 * field `location` names.
 */
export function PhasePanel({
  def,
  at,
  diagnostics,
  stored,
  onChange,
  onRemove,
  onClearStored,
}: {
  def: SpineDefinition;
  at: number;
  diagnostics: readonly TaskDiagnostic[];
  stored: readonly SpineStoredValue[];
  onChange: (next: SpineDefinition) => void;
  onRemove: () => void;
  onClearStored: (key: string) => void;
}) {
  const phase = def.spine[at];
  if (!phase) return null;
  const inputs = def.slots.filter((s) => s.type === "digital_in").map((s) => s.id);
  const outputs = def.slots.filter((s) => OUTPUT_TYPES.has(s.type)).map((s) => s.id);
  const lines = def.slots.filter((s) => s.type === "digital_out" && !s.mode).map((s) => s.id);

  const set = (key: keyof SpinePhase, value: unknown) => {
    const next = { ...phase } as Record<string, unknown>;
    const empty = value === undefined || value === "" || value === false || (Array.isArray(value) && value.length === 0);
    if (empty) delete next[key];
    else next[key] = value;
    onChange(setPhase(def, at, next as unknown as SpinePhase));
  };

  const fields = phaseFields(phase.phase);
  const exits = exitNotes(def, at);

  return (
    <div className="flex flex-col gap-3 border-t border-halo/60 pt-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] tracking-[0.14em] text-static uppercase">
          Step {at + 1} · {PHASE_LABEL[phase.phase] ?? phase.phase}
        </span>
        <span className="text-[11px] text-static/80">{PHASE_HELP[phase.phase]}</span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={onRemove}
          className="flex items-center gap-1 text-[11px] text-static transition-colors hover:text-status-error"
        >
          <Trash2 size={11} strokeWidth={1.75} /> Remove step
        </button>
      </div>
      {FIELD_GROUPS.map(({ group, label, help }) => {
        const mine = fields.filter((f) => f.group === group);
        if (mine.length === 0 && !(group === "ends" && exits.length)) return null;
        return (
          <section key={group} className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-[9px] tracking-[0.14em] text-static/60 uppercase">{label}</span>
              {help && <Note>{help}</Note>}
            </div>
            {mine.length > 0 && (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-x-4 gap-y-2">
                {mine.map((field) => {
                  const problems = diagnosticsAt([...diagnostics], `spine[${at}].${field.key}`);
                  return (
                    <Field key={field.key} label={field.label}>
                      <PhaseControl
                        field={field}
                        value={phase[field.key]}
                        options={{ input: inputs, inputs, outputs, line: lines }}
                        invalid={problems.length > 0}
                        title={problemTitle(problems)}
                        onChange={(value) => set(field.key, value)}
                      />
                    </Field>
                  );
                })}
              </div>
            )}
            {group === "ends" && exits.length > 0 && (
              <ul className="flex flex-col gap-0.5">
                {exits.map((e) => {
                  const note = e.outcome.includes("_") ? classNote(e.outcome) : null;
                  return (
                    <li key={e.exit} className="text-[11px] text-static">
                      <span className="text-starlight/90">{e.exit}</span>
                      {e.outcome && (
                        <>
                          {" → "}
                          <span className="text-starlight">{e.outcome.includes("_") ? classWord(e.outcome) : e.outcome}</span>
                          {note && <span className="text-static/70"> · {note}</span>}
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
      <StoredValues stored={stored} target={{ kind: "phase", index: at }} onClear={onClearStored} />
      <ProblemLines lines={targetLines(diagnostics, def, "phase", at)} onFix={(apply) => onChange(apply(def))} />
    </div>
  );
}

function PhaseControl({
  field,
  value,
  options,
  invalid,
  title,
  onChange,
}: {
  field: PhaseField;
  value: unknown;
  options: { input: string[]; inputs: string[]; outputs: string[]; line: string[] };
  invalid: boolean;
  title: string | undefined;
  onChange: (value: unknown) => void;
}) {
  const tone = invalid ? ("error" as const) : ("normal" as const);
  switch (field.kind) {
    case "input":
    case "line": {
      const choices = field.kind === "input" ? options.input : options.line;
      const current = typeof value === "string" ? value : "";
      const all = current && !choices.includes(current) ? [current, ...choices] : choices;
      return (
        <Select
          value={current}
          label={field.label}
          tone={tone}
          options={[{ value: "", label: field.optional ? "none" : "—" }, ...all.map((s) => ({ value: s, label: s }))]}
          onChange={onChange}
        />
      );
    }
    case "inputs":
    case "outputs":
      return (
        <SlotSet
          options={field.kind === "inputs" ? options.inputs : options.outputs}
          value={Array.isArray(value) ? (value as string[]) : []}
          label={field.label}
          invalid={invalid}
          title={title}
          onChange={onChange}
        />
      );
    case "edge":
      return (
        <Select
          value={typeof value === "string" ? value : "enter"}
          label={field.label}
          tone={tone}
          options={[
            { value: "enter", label: "entered" },
            { value: "exit", label: "left" },
          ]}
          onChange={(v) => onChange(v === "enter" ? undefined : v)}
        />
      );
    case "bool":
      return (
        <input
          type="checkbox"
          aria-label={field.label}
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="size-4 accent-[var(--color-pulsar)]"
        />
      );
    case "ints":
      return <IntsInput value={Array.isArray(value) ? (value as number[]) : []} label={field.label} invalid={invalid} title={title} onChange={onChange} />;
    case "ms":
    case "count": {
      const unit = field.kind === "ms" ? "ms" : undefined;
      if (field.optional) {
        return (
          <OptionalNumber
            value={typeof value === "number" ? value : undefined}
            initial={field.kind === "ms" ? 1000 : 5}
            label={field.label}
            min={field.kind === "ms" ? 0 : 1}
            invalid={invalid}
            title={title}
            {...(unit ? { unit } : {})}
            onChange={onChange}
          />
        );
      }
      return (
        <span className="flex items-center gap-1">
          <NumberInput
            value={typeof value === "number" ? value : ""}
            fallback={0}
            integer
            min={0}
            label={field.label}
            title={title}
            invalid={invalid}
            className="w-[96px]"
            onChange={onChange}
          />
          {unit && <span className="text-[10px] text-static">{unit}</span>}
        </span>
      );
    }
  }
}

/** A list of whole numbers, typed as "1, 2, 4, 6". Held as a draft while focused,
 *  so a trailing comma survives the keystroke. */
function IntsInput({
  value,
  label,
  invalid,
  title,
  onChange,
}: {
  value: number[];
  label: string;
  invalid: boolean;
  title: string | undefined;
  onChange: (next: number[]) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      type="text"
      aria-label={label}
      title={title}
      placeholder="none"
      value={draft ?? value.join(", ")}
      onFocus={() => setDraft(value.join(", "))}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(
          e.target.value
            .split(/[\s,]+/)
            .filter(Boolean)
            .map(Number)
            .filter((n) => Number.isInteger(n)),
        );
      }}
      onBlur={() => setDraft(null)}
      className={`rounded-sm border bg-nebula px-2.5 py-1.5 font-mono text-[12px] text-starlight focus:outline-none ${
        invalid ? "border-status-error" : "border-halo focus:border-pulsar"
      }`}
    />
  );
}
