import { ChevronDown, ChevronRight, Plus, Trash2, X } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { NumberInput, Select, TextInput } from "@/components/common/controls";
import type { RigDocument } from "@/lib/hardware/types";
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
import { problemLines } from "@/lib/taskdef/spineProblems";
import { channelChoices, channelGroups, classNote, mapSentences, msWord, responseWindow, rowSentence } from "@/lib/taskdef/spineWords";
import { diagnosticsAt } from "@/lib/taskdef/types";
import type { SpineStoredValue, SpineView, TaskDiagnostic } from "@/lib/ws/protocol";

import { ChannelSelect, Note, OptionalNumber, ProblemLines, StoredValues, problemTitle } from "./bits";

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
 * The trial types (the rows), one per kind of trial, with the channel that
 * plays each role and, under each, its contingency map as a sentence per
 * answer whose words are the controls (`TASKS.md#the-spine-editor`).
 *
 * A binding cell offers exactly the channels the preview says the slot can
 * bind on this rig (`SpineView.slots[].channels`): the frontend holds no
 * wiring. The rig document is read for each channel's Rig-tab label and kind,
 * display only, as the trial-table editor reads it. A row's problems are
 * listed under it as instructions, grouped by their fix, and its cells carry
 * their own, as the sidecar placed them.
 */
export function RowsTable({
  def,
  view,
  rig,
  outcomeClasses,
  diagnostics,
  stored,
  marked,
  onChange,
  onClearStored,
}: {
  def: SpineDefinition;
  view: SpineView | null;
  rig: RigDocument | null;
  outcomeClasses: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  stored: readonly SpineStoredValue[];
  marked: number | null;
  onChange: (next: SpineDefinition) => void;
  onClearStored: (key: string) => void;
}) {
  const windowAt = responseWindow(def);
  const window = windowAt >= 0 ? def.spine[windowAt] : undefined;
  const lines = def.slots.filter((s) => s.type === "digital_out" && !s.mode).map((s) => s.id);
  // An Outcome with no window before it pays the row's own probability.
  const outcomeAt = def.spine.findIndex((p) => p.phase === "outcome");
  const ownProbability = outcomeAt >= 0 && (windowAt < 0 || windowAt > outcomeAt);
  const driven = def.slots.filter((s) => driveOf(s.type, s.mode));
  const at = (path: string) => diagnosticsAt([...diagnostics], path);
  // Every column after the row number: name, the slots, reward, its probability, remove.
  const columns = def.slots.length + (ownProbability ? 4 : 3);
  const groupsOf = useMemo(
    () => def.slots.map((slot, s) => channelGroups(channelChoices(view?.slots[s]?.id === slot.id ? view.slots[s].channels : [], rig))),
    [def.slots, view, rig],
  );

  return (
    <div className="flex flex-col gap-2">
      <Roles def={def} diagnostics={diagnostics} onChange={onChange} />
      <div className="scrollbar-slim overflow-x-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">
              <th className={`${cell} text-left font-normal`}>#</th>
              <th className={`${cell} text-left font-normal`}>Name</th>
              {def.slots.map((slot) => (
                <th key={slot.id} className={`${cell} text-left font-normal normal-case tracking-normal`}>
                  <span className="font-mono text-[11px] text-starlight/90">{slot.id}</span>
                  <span className="ml-1 text-[9px] text-static/60">{slotTypeLabel(slot.type, slot.mode)}</span>
                </th>
              ))}
              <th className={`${cell} text-left font-normal`}>Reward ms</th>
              {ownProbability && <th className={`${cell} text-left font-normal`}>Pays on % of trials</th>}
            </tr>
          </thead>
          <tbody>
            {def.rows.map((row, r) => {
              const problems = diagnosticsOn(diagnostics, "row", r);
              const sentences = mapSentences(def, row, rig);
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
                      return (
                        <td key={slot.id} className={cell} title={problemTitle(here)}>
                          <ChannelSelect
                            value={row.bind[slot.id] ?? ""}
                            groups={groupsOf[s] ?? []}
                            label={`${slot.id} of trial type ${r + 1}`}
                            tone={here.length ? "error" : "normal"}
                            className="w-[140px]"
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
                        label={`Reward ms of trial type ${r + 1}`}
                        invalid={at(`rows[${r}].rewardMs`).length > 0}
                        className="w-[72px]"
                        onChange={(rewardMs) => onChange(setRow(def, r, { ...row, rewardMs }))}
                      />
                    </td>
                    {ownProbability && (
                      <td className={cell}>
                        <NumberInput
                          value={row.rewardPermille / 10}
                          fallback={100}
                          min={0}
                          max={100}
                          label={`Reward probability of trial type ${r + 1}, in percent`}
                          invalid={at(`rows[${r}].rewardPermille`).length > 0}
                          className="w-[72px]"
                          onChange={(percent) => onChange(setRow(def, r, { ...row, rewardPermille: Math.round(percent * 10) }))}
                        />
                      </td>
                    )}
                    <td className={`${cell} pt-2`}>
                      <button
                        type="button"
                        aria-label={`Remove trial type ${r + 1}`}
                        onClick={() => onChange(removeRow(def, r))}
                        className="text-static transition-colors hover:text-status-error"
                      >
                        <Trash2 size={12} strokeWidth={1.75} />
                      </button>
                    </td>
                  </tr>
                  <tr className={marked === r ? "bg-pulsar/10" : ""}>
                    <td />
                    <td colSpan={columns} className="px-1.5 pb-2">
                      <div className="flex flex-col gap-1">
                        {sentences.length === 0 && (
                          <Note className="text-static">{rowSentence(def, row, rig)}</Note>
                        )}
                        {sentences.map((sentence) => (
                          <MapLine
                            key={sentence.key}
                            response={sentence.key}
                            subject={sentence.subject}
                            entry={row.map?.[sentence.key]}
                            classes={outcomeClasses}
                            lines={lines}
                            lineWord={(slot) => {
                              const channel = row.bind[slot];
                              return channel ? channelChoices([channel], rig)[0]?.label ?? slot : slot;
                            }}
                            holdMs={sentence.key !== "timeout" ? window?.holdMs : undefined}
                            problems={at(`rows[${r}].map.${sentence.key}`)}
                            onChange={(entry) => onChange(setMapEntry(def, r, sentence.key, entry))}
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
                        {problems.length > 0 && (
                          <ProblemLines lines={problemLines(diagnostics, def, rig, r)} onFix={(apply) => onChange(apply(def))} />
                        )}
                      </div>
                    </td>
                  </tr>
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <ProblemLines lines={problemLines(diagnostics, def, rig, null).filter((l) => l.code !== "SPN103" && l.diagnostics[0]?.target.kind === "row")} onFix={(apply) => onChange(apply(def))} />
      <button
        type="button"
        onClick={() => onChange(addRow(def))}
        className="flex items-center gap-1 self-start text-[11px] text-static transition-colors hover:text-starlight"
      >
        <Plus size={12} strokeWidth={1.75} /> Add a trial type
        <span className="text-static/60">· copies the last one, unnamed</span>
      </button>
    </div>
  );
}

/** A row's name, held as typed. Unnamed is SPN108, said under the row. */
function NameInput({ value, invalid, onChange }: { value: string; invalid: boolean; onChange: (v: string) => void }) {
  return (
    <input
      type="text"
      aria-label="Trial type name"
      value={value}
      placeholder="name this trial type"
      onChange={(e) => onChange(e.target.value)}
      className={`w-[150px] rounded-sm border bg-nebula px-2 py-1.5 text-[12px] text-starlight placeholder:text-static/60 focus:outline-none ${
        invalid ? "border-status-error" : "border-halo focus:border-pulsar"
      }`}
    />
  );
}

/**
 * One answer of the contingency map as a sentence whose words are the
 * controls: "Left well → [correct], pays [left water] on [100] % of trials,
 * [held 200 ms] · then [the ITI]". The class's note follows where it
 * surprises (`spineWords.classNote`).
 */
function MapLine({
  response,
  subject,
  entry,
  classes,
  lines,
  lineWord,
  holdMs,
  problems,
  onChange,
}: {
  response: string;
  subject: string;
  entry: MapEntry | undefined;
  classes: readonly string[];
  lines: readonly string[];
  /** A reward line slot by the channel the row binds it to. */
  lineWord: (slot: string) => string;
  /** The window's hold, when this answer can be held. */
  holdMs: number | undefined;
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
    if (next.penaltyMs === undefined) delete next.penaltyMs;
    onChange(next);
  };
  const note = entry ? classNote(entry.outcome) : null;
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-static" title={problemTitle(problems)}>
      <span className={`min-w-[92px] ${problems.length ? "text-status-error" : "text-starlight/90"}`}>{subject}</span>
      <span>→</span>
      <Select
        value={entry?.outcome ?? ""}
        label={`What ${response === "timeout" ? "no answer" : response} means`}
        tone={problems.length && !entry ? "error" : "normal"}
        compact
        options={[{ value: "", label: "not mapped yet" }, ...classes.map((c) => ({ value: c, label: classLabel(c) }))]}
        onChange={(outcome) => (outcome ? set({ outcome }) : onChange(null))}
      />
      {entry && (
        <>
          <span>· pays</span>
          <Select
            value={entry.line ?? ""}
            label={`Reward line of ${response}`}
            compact
            options={[{ value: "", label: "nothing" }, ...lines.map((l) => ({ value: l, label: lineWord(l) }))]}
            onChange={(line) => set({ line: line || undefined })}
          />
          {entry.line && (
            <>
              <span>on</span>
              <NumberInput
                value={(entry.rewardPermille ?? 1000) / 10}
                fallback={100}
                min={0}
                max={100}
                label={`How often ${response} pays, in percent`}
                className="w-[56px] !py-0.5 text-[11px]"
                onChange={(percent) => set({ rewardPermille: Math.round(percent * 10) })}
              />
              <span>% of trials</span>
            </>
          )}
          {holdMs !== undefined && (
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                aria-label={`${response} must be held ${msWord(holdMs)}`}
                checked={entry.hold === true}
                onChange={(e) => set({ hold: e.target.checked })}
                className="accent-[var(--color-pulsar)]"
              />
              held {msWord(holdMs)}
            </label>
          )}
          <span>· then</span>
          {entry.penaltyMs === undefined ? (
            <>
              <span className="text-starlight/90">the ITI</span>
              <button
                type="button"
                onClick={() => set({ penaltyMs: 20000 })}
                className="rounded-sm border border-dashed border-halo px-1.5 text-[10px] text-static transition-colors hover:border-static/60 hover:text-starlight"
                title="A penalty replaces the ITI after this answer: the box waits this long before the next trial"
              >
                + penalty instead
              </button>
            </>
          ) : (
            <>
              <span>a</span>
              <OptionalNumber
                value={entry.penaltyMs}
                initial={20000}
                label={`Penalty after ${response}`}
                min={0}
                unit="ms"
                title="Waits this long before the next trial, in place of the ITI"
                onChange={(penaltyMs) => set({ penaltyMs })}
              />
              <span>penalty instead of the ITI</span>
            </>
          )}
          {note && <span className="w-full pl-[100px] text-[10px] text-static/70 sm:w-auto sm:pl-0">· {note}</span>}
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

/**
 * The roles: each part in the trial the steps name (the port, the sample,
 * the left well), which each trial type binds to a channel of this rig.
 * Adding and removing one sits behind a disclosure: a first task has every
 * role its seed needs, and a role removed is a step left pointing at nothing.
 */
function Roles({
  def,
  diagnostics,
  onChange,
}: {
  def: SpineDefinition;
  diagnostics: readonly TaskDiagnostic[];
  onChange: (next: SpineDefinition) => void;
}) {
  const [open, setOpen] = useState(false);
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
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">Roles</span>
        <span className="text-[11px] text-static">
          {def.slots.map((slot, i) => (
            <span key={`${slot.id}-${i}`} className={diagnosticsOn(diagnostics, "slot", i).length ? "text-status-error" : ""}>
              {i > 0 && " · "}
              <span className="font-mono text-starlight/90">{slot.id}</span> <span className="text-static/60">{slotTypeLabel(slot.type, slot.mode)}</span>
            </span>
          ))}
        </span>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="flex items-center gap-0.5 text-[11px] text-static transition-colors hover:text-starlight"
        >
          {open ? <ChevronDown size={11} strokeWidth={1.75} /> : <ChevronRight size={11} strokeWidth={1.75} />}
          {open ? "done" : "add or remove a role"}
        </button>
      </div>
      <Note>
        A role is a part in the trial: the port the animal pokes, the sample it smells, the well it answers at, the line that pays. Each
        trial type below says which channel on this rig plays it.
      </Note>
      {open && (
        <div className="flex flex-wrap items-center gap-1.5">
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
                  aria-label={`Remove role ${slot.id}`}
                  title="A step still naming this role will be flagged"
                  onClick={() => onChange(removeSlot(def, i))}
                  className="text-static transition-colors hover:text-status-error"
                >
                  <X size={10} strokeWidth={1.75} />
                </button>
              </span>
            );
          })}
          <span className="flex items-center gap-1">
            <TextInput value={id} onChange={setId} onSubmit={add} placeholder="new role" label="New role id" mono className="w-[110px] !py-1" />
            <Select
              value={type}
              label="New role type"
              compact
              options={SLOT_TYPES.map((t) => ({ value: t.value as string, label: t.label }))}
              onChange={setType}
            />
            <button
              type="button"
              onClick={add}
              disabled={!id.trim()}
              className="flex items-center gap-1 text-[11px] text-static transition-colors hover:text-starlight disabled:opacity-40"
            >
              <Plus size={11} strokeWidth={1.75} /> role
            </button>
          </span>
        </div>
      )}
      {problems.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-[11px] text-status-error">
          {problems.map((d, i) => (
            <li key={i}>
              <span className="font-mono text-[10px]">{d.code}</span> {d.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
