import { ArrowLeftRight, ChevronDown, ChevronRight, Plus, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

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
import { problemLines, wiringLines } from "@/lib/taskdef/spineProblems";
import {
  bindShared,
  channelChoices,
  channelGroups,
  classNote,
  mapSentences,
  msWord,
  responseWindow,
  roleScopes,
  rowSentence,
  sharedChannel,
} from "@/lib/taskdef/spineWords";
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

const LABEL = "font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase";

/**
 * The trial types (`TASKS.md#the-spine-editor`). A **Wiring** line binds each
 * role that is the same in every trial type once; a role two trial types bind
 * differently is per type and appears on each row. So a row shows only what
 * makes it a trial type: its name, the roles that differ, its reward and its
 * contingency map as a sentence per answer whose words are the controls.
 *
 * A binding cell offers exactly the channels the preview says the slot can
 * bind on this rig (`SpineView.slots[].channels`): the frontend holds no
 * wiring. The rig document is read for each channel's Rig-tab label and kind,
 * display only, as the trial-table editor reads it. Which roles are shared is
 * read off the bindings (`spineWords.roleScopes`); a row can also show a
 * shared role to choose differently, which makes it per type.
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
  // An Outcome with no window before it pays the row's own probability.
  const outcomeAt = def.spine.findIndex((p) => p.phase === "outcome");
  const ownProbability = outcomeAt >= 0 && (windowAt < 0 || windowAt > outcomeAt);
  const driven = def.slots.filter((s) => driveOf(s.type, s.mode));
  const at = (path: string) => diagnosticsAt([...diagnostics], path);
  const groupsOf = useMemo(
    () => Object.fromEntries(def.slots.map((slot, s) => [slot.id, channelGroups(channelChoices(view?.slots[s]?.id === slot.id ? view.slots[s].channels : [], rig))])),
    [def.slots, view, rig],
  );
  const scopes = roleScopes(def);
  const shared = def.slots.filter((s) => scopes[s.id] === "shared").map((s) => s.id);
  const perType = def.slots.filter((s) => scopes[s.id] === "per-type").map((s) => s.id);
  /** Shared roles a row shows anyway, to choose differently: row index → roles. */
  const [exposed, setExposed] = useState<Record<number, string[]>>({});
  const expose = (r: number | null, slot: string) =>
    setExposed((e) => {
      const next = { ...e };
      for (const i of r === null ? def.rows.map((_, i) => i) : [r]) next[i] = [...new Set([...(next[i] ?? []), slot])];
      return next;
    });
  const unexpose = (slot: string) => setExposed((e) => Object.fromEntries(Object.entries(e).map(([k, v]) => [k, v.filter((s) => s !== slot)])));
  const bindingProblems = (slot: string) => def.rows.flatMap((_, r) => at(`rows[${r}].bind.${slot}`));

  return (
    <div className="flex flex-col gap-3">
      <Roles def={def} diagnostics={diagnostics} onChange={onChange} />

      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <span className={`${LABEL} self-center`}>Wiring</span>
          {shared.map((slot) => {
            const problems = bindingProblems(slot);
            return (
              <label key={slot} className="flex flex-col gap-0.5" title={problemTitle(problems)}>
                <span className="flex items-center gap-1 font-mono text-[10px] text-starlight/90">
                  {slot}
                  <button
                    type="button"
                    aria-label={`Choose ${slot} per trial type`}
                    title="Choose this role per trial type instead"
                    onClick={() => expose(null, slot)}
                    className="text-static/50 transition-colors hover:text-starlight"
                  >
                    <ArrowLeftRight size={9} strokeWidth={1.75} />
                  </button>
                </span>
                <ChannelSelect
                  value={sharedChannel(def, slot)}
                  groups={groupsOf[slot] ?? []}
                  label={`Channel for ${slot}, in every trial type`}
                  tone={problems.length ? "error" : "normal"}
                  className="w-[150px]"
                  onChange={(channel) => onChange(bindShared(def, slot, channel))}
                />
              </label>
            );
          })}
          {shared.length === 0 && <span className="text-[11px] text-static">every role differs per trial type</span>}
        </div>
        {perType.length > 0 && (
          <p className="flex flex-wrap items-center gap-x-2 text-[11px] text-static">
            <span>Each trial type chooses:</span>
            {perType.map((slot) => (
              <span key={slot} className="flex items-center gap-1">
                <span className="font-mono text-starlight/90">{slot}</span>
                <button
                  type="button"
                  onClick={() => {
                    unexpose(slot);
                    onChange(bindShared(def, slot, sharedChannel(def, slot)));
                  }}
                  className="text-[10px] text-pulsar transition-colors hover:text-starlight"
                  title="Bind every trial type as the first does"
                >
                  make it the same for all
                </button>
              </span>
            ))}
          </p>
        )}
        <Note>
          A role is a part in the trial: the port, the sample, the wells, the line that pays. Wiring binds a role for every trial type at
          once; a role one trial type binds differently moves onto the rows.
        </Note>
        <ProblemLines lines={wiringLines(diagnostics, rig, shared)} onFix={(apply) => onChange(apply(def))} />
      </div>

      <div className="flex flex-col divide-y divide-halo/50">
        {def.rows.map((row, r) => {
          const problems = diagnosticsOn(diagnostics, "row", r);
          const roles = [...perType, ...(exposed[r] ?? []).filter((s) => !perType.includes(s) && def.slots.some((x) => x.id === s))];
          const hidden = shared.filter((s) => !roles.includes(s));
          return (
            <div id={`spine-row-${r}`} key={row.id} className={`flex flex-col gap-1.5 py-2 transition-colors ${marked === r ? "bg-pulsar/10" : ""}`}>
              <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
                <span className="self-center font-mono text-[10px] text-static" title={row.id}>
                  {r + 1}
                </span>
                <label className="flex flex-col gap-0.5">
                  <span className={LABEL}>Name</span>
                  <NameInput value={row.name} invalid={at(`rows[${r}].name`).length > 0} onChange={(name) => onChange(setRow(def, r, { ...row, name }))} />
                </label>
                {roles.map((slot) => {
                  const here = at(`rows[${r}].bind.${slot}`);
                  return (
                    <label key={slot} className="flex flex-col gap-0.5" title={problemTitle(here)}>
                      <span className="font-mono text-[10px] text-starlight/90">
                        {slot} <span className="text-static/60">{slotTypeLabel(def.slots.find((s) => s.id === slot)?.type ?? "", def.slots.find((s) => s.id === slot)?.mode)}</span>
                      </span>
                      <ChannelSelect
                        value={row.bind[slot] ?? ""}
                        groups={groupsOf[slot] ?? []}
                        label={`${slot} of trial type ${r + 1}`}
                        tone={here.length ? "error" : "normal"}
                        className="w-[150px]"
                        onChange={(channel) => onChange(setBinding(def, r, slot, channel))}
                      />
                    </label>
                  );
                })}
                {hidden.length > 0 && (
                  <label className="flex flex-col gap-0.5">
                    <span className={LABEL}>differs here</span>
                    <select
                      aria-label={`A role trial type ${r + 1} chooses for itself`}
                      value=""
                      onChange={(e) => e.target.value && expose(r, e.target.value)}
                      className="rounded-sm border border-dashed border-halo bg-nebula px-2 py-1.5 text-[11px] text-static"
                    >
                      <option value="">choose a role…</option>
                      {hidden.map((slot) => (
                        <option key={slot} value={slot}>
                          {slot}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label className="flex flex-col gap-0.5">
                  <span className={LABEL}>Reward ms</span>
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
                </label>
                {ownProbability && (
                  <label className="flex flex-col gap-0.5">
                    <span className={LABEL}>Pays on % of trials</span>
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
                  </label>
                )}
                <button
                  type="button"
                  aria-label={`Remove trial type ${r + 1}`}
                  onClick={() => onChange(removeRow(def, r))}
                  className="self-center text-static transition-colors hover:text-status-error"
                >
                  <Trash2 size={12} strokeWidth={1.75} />
                </button>
              </div>
              <div className="flex flex-col gap-1 pl-5">
                <RowAnswers def={def} r={r} rig={rig} outcomeClasses={outcomeClasses} diagnostics={diagnostics} onChange={onChange} />
                {driven.map((slot) => (
                  <DriveLine
                    key={slot.id}
                    slot={slot.id}
                    kind={driveOf(slot.type, slot.mode) ?? ""}
                    values={row.drive?.[slot.id] ?? {}}
                    problems={at(`rows[${r}].drive.${slot.id}`)}
                    onChange={(values) => onChange(setRow(def, r, { ...row, drive: { ...(row.drive ?? {}), [slot.id]: values } }))}
                  />
                ))}
                <StoredValues stored={stored} target={{ kind: "row", index: r }} onClear={onClearStored} />
                {problems.length > 0 && <ProblemLines lines={problemLines(diagnostics, def, rig, r, shared)} onFix={(apply) => onChange(apply(def))} />}
              </div>
            </div>
          );
        })}
      </div>
      <ProblemLines
        lines={problemLines(diagnostics, def, rig, null).filter((l) => l.code !== "SPN103" && l.diagnostics[0]?.target.kind === "row")}
        onFix={(apply) => onChange(apply(def))}
      />
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

/**
 * One trial type's contingency map, a sentence per answer whose words are the
 * controls (`MapLine`); a row with no window says what every trial of it does.
 * The guide's answers step shows the same lines (`SpineGuide`).
 */
export function RowAnswers({
  def,
  r,
  rig,
  outcomeClasses,
  diagnostics,
  onChange,
}: {
  def: SpineDefinition;
  r: number;
  rig: RigDocument | null;
  outcomeClasses: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  onChange: (next: SpineDefinition) => void;
}) {
  const row = def.rows[r]!;
  const windowAt = responseWindow(def);
  const window = windowAt >= 0 ? def.spine[windowAt] : undefined;
  const lines = def.slots.filter((s) => s.type === "digital_out" && !s.mode).map((s) => s.id);
  const sentences = mapSentences(def, row, rig);
  return (
    <>
      {sentences.length === 0 && <Note className="text-static">{rowSentence(def, row, rig)}</Note>}
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
            return channel ? (channelChoices([channel], rig)[0]?.label ?? slot) : slot;
          }}
          holdMs={sentence.key !== "timeout" ? window?.holdMs : undefined}
          problems={diagnosticsAt([...diagnostics], `rows[${r}].map.${sentence.key}`)}
          onChange={(entry) => onChange(setMapEntry(def, r, sentence.key, entry))}
        />
      ))}
    </>
  );
}

/** A row's name, held as typed. Unnamed is SPN108, said under the row. */
export function NameInput({ value, invalid, onChange }: { value: string; invalid: boolean; onChange: (v: string) => void }) {
  return (
    <input
      type="text"
      aria-label="Trial type name"
      value={value}
      placeholder="name this trial type"
      onChange={(e) => onChange(e.target.value)}
      className={`w-[170px] rounded-sm border bg-nebula px-2 py-1.5 text-[12px] text-starlight placeholder:text-static/60 focus:outline-none ${
        invalid ? "border-status-error" : "border-halo focus:border-pulsar"
      }`}
    />
  );
}

/**
 * One answer of the contingency map as a sentence whose words are the
 * controls: "Left well → [correct] · pays [left water] on [100] % of trials ·
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
          {note && <span className="text-[10px] text-static/70">· {note}</span>}
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
      <span className={`w-[92px] truncate font-mono ${problems.length ? "text-status-error" : "text-starlight/90"}`}>{slot}</span>
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
 * The roles the steps name, behind a disclosure: a first task has every role
 * its seed needs, and a role removed is a step left pointing at nothing.
 */
function Roles({ def, diagnostics, onChange }: { def: SpineDefinition; diagnostics: readonly TaskDiagnostic[]; onChange: (next: SpineDefinition) => void }) {
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
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 self-start text-[11px] text-static transition-colors hover:text-starlight"
      >
        {open ? <ChevronDown size={11} strokeWidth={1.75} /> : <ChevronRight size={11} strokeWidth={1.75} />}
        <span className={LABEL}>Roles</span>
        <span>
          {def.slots.length} · {open ? "done" : "add or remove one"}
        </span>
        {problems.length > 0 && <span className="text-status-error">{problems.length} problem{problems.length === 1 ? "" : "s"}</span>}
      </button>
      {open && (
        <div className="flex flex-wrap items-center gap-1.5">
          {def.slots.map((slot, i) => {
            const bad = diagnosticsOn(diagnostics, "slot", i).length > 0;
            return (
              <span key={`${slot.id}-${i}`} className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] ${bad ? "border-status-error" : "border-halo"}`}>
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
            <Select value={type} label="New role type" compact options={SLOT_TYPES.map((t) => ({ value: t.value as string, label: t.label }))} onChange={setType} />
            <button type="button" onClick={add} disabled={!id.trim()} className="flex items-center gap-1 text-[11px] text-static transition-colors hover:text-starlight disabled:opacity-40">
              <Plus size={11} strokeWidth={1.75} /> role
            </button>
          </span>
        </div>
      )}
      {open && problems.length > 0 && (
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
