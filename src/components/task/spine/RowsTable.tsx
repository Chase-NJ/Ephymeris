import { Plus, Trash2, X } from "lucide-react";
import { Fragment, useState } from "react";

import { NumberInput, Select, TextInput } from "@/components/common/controls";
import {
  addRow,
  addSlot,
  diagnosticsOn,
  removeRow,
  removeSlot,
  setBinding,
  setMapEntry,
  setRow,
  type MapEntry,
  type SpineDefinition,
} from "@/lib/taskdef/spine";
import { SLOT_TYPES, classLabel, slotTypeLabel } from "@/lib/taskdef/spineLabels";
import { diagnosticsAt } from "@/lib/taskdef/types";
import type { SpineStoredValue, SpineView, TaskDiagnostic } from "@/lib/ws/protocol";

import { ProblemLines, StoredValues, problemTitle } from "./bits";

/** A driven slot's values on a row (`TASKS.md#driven-outputs`): key, label, unit, initial. */
const DRIVE: Record<string, [string, string, string, number][]> = {
  pwm: [["duty", "duty", "", 128]],
  tone: [["hz", "tone", "Hz", 2000]],
  train: [
    ["hz", "rate", "Hz", 20],
    ["widthMs", "width", "ms", 5],
    ["ms", "length", "ms", 1000],
  ],
};

function driveOf(type: string, mode?: string | null): string | null {
  if (type === "pwm_out") return "pwm";
  if (type === "tone_out") return "tone";
  if (type === "digital_out" && mode === "train") return "train";
  return null;
}

const cell = "px-1.5 py-1 align-top";

/**
 * The rows (trial types) with one column per slot, and under each its
 * contingency map and driven values (`TASKS.md#the-spine-editor`).
 *
 * A binding cell offers exactly the channels the preview says the slot can
 * bind on this rig (`SpineView.slots[].channels`): the frontend holds no
 * wiring. A row's problems are listed under it and its cells carry their own,
 * as the sidecar placed them.
 */
export function RowsTable({
  def,
  view,
  outcomeClasses,
  diagnostics,
  stored,
  marked,
  onChange,
  onClearStored,
}: {
  def: SpineDefinition;
  view: SpineView | null;
  outcomeClasses: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  stored: readonly SpineStoredValue[];
  marked: number | null;
  onChange: (next: SpineDefinition) => void;
  onClearStored: (key: string) => void;
}) {
  const window = def.spine.find((p) => p.phase === "response");
  const responses = window ? [...(window.responses ?? []), "timeout"] : [];
  const lines = def.slots.filter((s) => s.type === "digital_out" && !s.mode).map((s) => s.id);
  // An Outcome with no window before it pays the row's own probability.
  const firstWindow = def.spine.findIndex((p) => p.phase === "response");
  const outcomeAt = def.spine.findIndex((p) => p.phase === "outcome");
  const ownProbability = outcomeAt >= 0 && (firstWindow < 0 || firstWindow > outcomeAt);
  const driven = def.slots.filter((s) => driveOf(s.type, s.mode));
  const at = (path: string) => diagnosticsAt([...diagnostics], path);
  // Every column after the row number: name, the slots, reward, its probability, remove.
  const columns = def.slots.length + (ownProbability ? 4 : 3);

  return (
    <div className="flex flex-col gap-2">
      <Slots def={def} diagnostics={diagnostics} onChange={onChange} />
      <div className="scrollbar-slim overflow-x-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">
              <th className={`${cell} text-left font-normal`}>#</th>
              <th className={`${cell} text-left font-normal`}>Name</th>
              {def.slots.map((slot) => (
                <th key={slot.id} className={`${cell} text-left font-normal normal-case tracking-normal`}>
                  <span className="font-mono text-[11px] text-starlight/90">{slot.id}</span>
                </th>
              ))}
              <th className={`${cell} text-left font-normal`}>Reward ms</th>
              {ownProbability && <th className={`${cell} text-left font-normal`}>Reward ‰</th>}
            </tr>
          </thead>
          <tbody>
            {def.rows.map((row, r) => {
              const problems = diagnosticsOn(diagnostics, "row", r);
              return (
                <Fragment key={row.id}>
                  <tr
                    id={`spine-row-${r}`}
                    className={`border-t border-halo/50 transition-colors ${marked === r ? "bg-pulsar/10" : ""}`}
                  >
                    <td className={`${cell} pt-2 font-mono text-[10px] text-static`} title={row.id}>
                      {r + 1}
                    </td>
                    <td className={cell}>
                      <NameInput
                        value={row.name}
                        invalid={at(`rows[${r}].name`).length > 0}
                        onChange={(name) => onChange(setRow(def, r, { ...row, name }))}
                      />
                    </td>
                    {def.slots.map((slot, s) => {
                      const here = at(`rows[${r}].bind.${slot.id}`);
                      const offered = view?.slots[s]?.id === slot.id ? view.slots[s].channels : [];
                      const current = row.bind[slot.id] ?? "";
                      const options = current && !offered.includes(current) ? [current, ...offered] : offered;
                      return (
                        <td key={slot.id} className={cell} title={problemTitle(here)}>
                          <Select
                            value={current}
                            label={`${slot.id} of row ${r + 1}`}
                            tone={here.length ? "error" : "normal"}
                            className="w-[132px]"
                            options={[{ value: "", label: "—" }, ...options.map((c) => ({ value: c, label: c }))]}
                            onChange={(channel) => onChange(setBinding(def, r, slot.id, channel))}
                          />
                        </td>
                      );
                    })}
                    <td className={cell}>
                      <NumberInput
                        value={row.rewardMs}
                        fallback={100}
                        integer
                        min={0}
                        label={`Reward ms of row ${r + 1}`}
                        invalid={at(`rows[${r}].rewardMs`).length > 0}
                        className="w-[72px]"
                        onChange={(rewardMs) => onChange(setRow(def, r, { ...row, rewardMs }))}
                      />
                    </td>
                    {ownProbability && (
                      <td className={cell}>
                        <NumberInput
                          value={row.rewardPermille}
                          fallback={1000}
                          integer
                          min={0}
                          max={1000}
                          label={`Reward probability of row ${r + 1}`}
                          invalid={at(`rows[${r}].rewardPermille`).length > 0}
                          className="w-[72px]"
                          onChange={(rewardPermille) => onChange(setRow(def, r, { ...row, rewardPermille }))}
                        />
                      </td>
                    )}
                    <td className={`${cell} pt-2`}>
                      <button
                        type="button"
                        aria-label={`Remove row ${r + 1}`}
                        onClick={() => onChange(removeRow(def, r))}
                        className="text-static transition-colors hover:text-status-error"
                      >
                        <Trash2 size={12} strokeWidth={1.75} />
                      </button>
                    </td>
                  </tr>
                  {(responses.length > 0 || driven.length > 0 || problems.length > 0) && (
                    <tr className={marked === r ? "bg-pulsar/10" : ""}>
                      <td />
                      <td colSpan={columns} className="px-1.5 pb-2">
                        <div className="flex flex-col gap-1">
                          {responses.map((key) => (
                            <MapLine
                              key={key}
                              response={key}
                              entry={row.map?.[key]}
                              classes={outcomeClasses}
                              lines={lines}
                              canHold={key !== "timeout" && window?.holdMs !== undefined}
                              problems={at(`rows[${r}].map.${key}`)}
                              onChange={(entry) => onChange(setMapEntry(def, r, key, entry))}
                            />
                          ))}
                          {driven.map((slot) => (
                            <DriveLine
                              key={slot.id}
                              slot={slot.id}
                              kind={driveOf(slot.type, slot.mode) ?? ""}
                              values={row.drive?.[slot.id] ?? {}}
                              problems={at(`rows[${r}].drive.${slot.id}`)}
                              onChange={(values) =>
                                onChange(setRow(def, r, { ...row, drive: { ...(row.drive ?? {}), [slot.id]: values } }))
                              }
                            />
                          ))}
                          <StoredValues stored={stored} target={{ kind: "row", index: r }} onClear={onClearStored} />
                          <ProblemLines diagnostics={problems} />
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <button
        type="button"
        onClick={() => onChange(addRow(def))}
        className="flex items-center gap-1 self-start text-[11px] text-static transition-colors hover:text-starlight"
      >
        <Plus size={12} strokeWidth={1.75} /> Add a row
      </button>
    </div>
  );
}

/** A row's name, held as typed. Unnamed is SPN108, said under the row. */
function NameInput({ value, invalid, onChange }: { value: string; invalid: boolean; onChange: (v: string) => void }) {
  return (
    <input
      type="text"
      aria-label="Row name"
      value={value}
      placeholder="name this row"
      onChange={(e) => onChange(e.target.value)}
      className={`w-[140px] rounded-sm border bg-nebula px-2 py-1.5 text-[12px] text-starlight placeholder:text-static/60 focus:outline-none ${
        invalid ? "border-status-error" : "border-halo focus:border-pulsar"
      }`}
    />
  );
}

/** One entry of the contingency map: a response (or the timeout) → a class, a line, a probability, a hold. */
function MapLine({
  response,
  entry,
  classes,
  lines,
  canHold,
  problems,
  onChange,
}: {
  response: string;
  entry: MapEntry | undefined;
  classes: readonly string[];
  lines: readonly string[];
  canHold: boolean;
  problems: TaskDiagnostic[];
  onChange: (entry: MapEntry | null) => void;
}) {
  const set = (patch: { [K in keyof MapEntry]?: MapEntry[K] | undefined }) => {
    const next = { ...(entry ?? { outcome: classes[0] ?? "correct" }), ...patch } as MapEntry;
    if (!next.line) {
      delete next.line;
      delete next.rewardPermille;
    } else if (next.rewardPermille === undefined) next.rewardPermille = 1000;
    if (!next.hold) delete next.hold;
    onChange(next);
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-static" title={problemTitle(problems)}>
      <span className={`w-[92px] truncate font-mono ${problems.length ? "text-status-error" : "text-starlight/90"}`}>
        {response}
      </span>
      <span>→</span>
      <Select
        value={entry?.outcome ?? ""}
        label={`Outcome of ${response}`}
        tone={problems.length && !entry ? "error" : "normal"}
        className="!py-1 text-[11px]"
        options={[{ value: "", label: "not mapped" }, ...classes.map((c) => ({ value: c, label: classLabel(c) }))]}
        onChange={(outcome) => (outcome ? set({ outcome }) : onChange(null))}
      />
      {entry && (
        <>
          <span>pays</span>
          <Select
            value={entry.line ?? ""}
            label={`Reward line of ${response}`}
            className="!py-1 text-[11px]"
            options={[{ value: "", label: "nothing" }, ...lines.map((l) => ({ value: l, label: l }))]}
            onChange={(line) => set({ line: line || undefined })}
          />
          {entry.line && (
            <>
              <NumberInput
                value={entry.rewardPermille ?? 1000}
                fallback={1000}
                integer
                min={0}
                max={1000}
                label={`Reward probability of ${response}`}
                className="w-[64px] !py-1 text-[11px]"
                onChange={(rewardPermille) => set({ rewardPermille })}
              />
              <span>‰</span>
            </>
          )}
          {canHold && (
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={entry.hold === true}
                onChange={(e) => set({ hold: e.target.checked })}
                className="accent-[var(--color-pulsar)]"
              />
              held
            </label>
          )}
        </>
      )}
    </div>
  );
}

/** A driven output slot's values on one row. */
function DriveLine({
  slot,
  kind,
  values,
  problems,
  onChange,
}: {
  slot: string;
  kind: string;
  values: Record<string, number>;
  problems: TaskDiagnostic[];
  onChange: (values: Record<string, number>) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-static" title={problemTitle(problems)}>
      <span className={`w-[92px] truncate font-mono ${problems.length ? "text-status-error" : "text-starlight/90"}`}>
        {slot}
      </span>
      {(DRIVE[kind] ?? []).map(([key, label, unit, initial]) => (
        <span key={key} className="flex items-center gap-1">
          <span>{label}</span>
          <NumberInput
            value={values[key] ?? ""}
            fallback={initial}
            integer
            min={0}
            label={`${label} of ${slot}`}
            invalid={problems.some((d) => d.location.endsWith(`.${key}`))}
            className="w-[72px] !py-1 text-[11px]"
            onChange={(v) => onChange({ ...values, [key]: v })}
          />
          {unit && <span>{unit}</span>}
        </span>
      ))}
    </div>
  );
}

/** The spine's slots: each role's id and type, with a way to add and remove one. */
function Slots({
  def,
  diagnostics,
  onChange,
}: {
  def: SpineDefinition;
  diagnostics: readonly TaskDiagnostic[];
  onChange: (next: SpineDefinition) => void;
}) {
  const [id, setId] = useState("");
  const [type, setType] = useState<string>("digital_in");
  const add = () => {
    const name = id.trim();
    if (!name) return;
    const [slotType = "digital_in", mode] = type.split(":");
    onChange(addSlot(def, mode ? { id: name, type: slotType, mode } : { id: name, type: slotType }));
    setId("");
  };
  const problems = def.slots.flatMap((_, i) => diagnosticsOn(diagnostics, "slot", i));
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">Slots</span>
        {def.slots.map((slot, i) => {
          const bad = diagnosticsOn(diagnostics, "slot", i).length > 0;
          return (
            <span
              key={`${slot.id}-${i}`}
              className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] ${
                bad ? "border-status-error" : "border-halo"
              }`}
            >
              <span className="font-mono text-starlight/90">{slot.id}</span>
              <span className="text-static">{slotTypeLabel(slot.type, slot.mode)}</span>
              <button
                type="button"
                aria-label={`Remove slot ${slot.id}`}
                onClick={() => onChange(removeSlot(def, i))}
                className="text-static transition-colors hover:text-status-error"
              >
                <X size={10} strokeWidth={1.75} />
              </button>
            </span>
          );
        })}
        <span className="flex items-center gap-1">
          <TextInput value={id} onChange={setId} onSubmit={add} placeholder="new slot" label="New slot id" mono className="w-[110px] !py-1" />
          <Select
            value={type}
            label="New slot type"
            className="!py-1 text-[11px]"
            options={SLOT_TYPES.map((t) => ({ value: t.value as string, label: t.label }))}
            onChange={setType}
          />
          <button
            type="button"
            onClick={add}
            disabled={!id.trim()}
            className="flex items-center gap-1 text-[11px] text-static transition-colors hover:text-starlight disabled:opacity-40"
          >
            <Plus size={11} strokeWidth={1.75} /> slot
          </button>
        </span>
      </div>
      <ProblemLines diagnostics={problems} />
    </div>
  );
}
