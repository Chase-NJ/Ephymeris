import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Dropdown, type DropdownOption } from "@/components/common/Dropdown";
import { NumberInput } from "@/components/common/controls";
import { colorForIndex } from "@/lib/analytics/view";
import type { RigDocument } from "@/lib/hardware/types";
import { springSnappy } from "@/lib/motion";
import { codeNumber, declaredOnset, lineOptions } from "@/lib/taskdef/lines";
import { modeInfo, presentsNoGo, readsWeights } from "@/lib/taskdef/selection";
import { blankTrial, channelLabel, diagnosticsAt } from "@/lib/taskdef/types";
import type { SelectionMode, TaskDiagnostic, TrialTypeDef } from "@/lib/taskdef/types";
import type { StrobeVocabulary } from "@/lib/ws/protocol";

import { Panel } from "./Panel";

/** A two-line row and a one-line row, in px — what the density choice budgets. */
const COMFORTABLE_H = 52;
const COMPACT_H = 30;

/**
 * The trial types — which odor means which answer, and what pays for it
 * (`TASKS.md#trial-types`).
 *
 * THE SCREEN THIS WHOLE SYSTEM EXISTS FOR, drawn as one row per condition so
 * every condition is on screen beside the machine at once.
 *
 * THE ODOR LINE IS THE ONE CHOICE. Its onset code is the line's own,
 * declared on the Rig tab (`TASKS.md#onset-codes`), so picking a line writes
 * both and the code is shown, never picked. A line another row already
 * presents is listed but disabled — one line, one code, one condition.
 *
 * ROW ORDER IS THE CONTRACT. Slot i is pool weight PW<i+1> and reward volume
 * RW<i+1> and `kTrials[i]` in the generated firmware, so there is no reorder,
 * and the weight and reward columns live ON the row: the generator reads them
 * there and nowhere else.
 *
 * TWO KINDS OF NAME. The rig's channel label ("sandalwood") follows the wiring
 * and never enters the profile; the row's own name ("Go right") is the
 * condition, titles every chart, and is required (TSK110).
 */
export function TrialTypes({
  trials,
  mode,
  rig,
  vocabulary,
  diagnostics,
  conditionOfRow,
  litReward,
  activeRow,
  onHoverRow,
  onChange,
}: {
  trials: TrialTypeDef[];
  mode: SelectionMode;
  rig: RigDocument | null;
  vocabulary: StrobeVocabulary | null;
  diagnostics: TaskDiagnostic[];
  /** The machine's condition id for a row, so a row hover lights its tick. */
  conditionOfRow: (row: number) => string | null;
  /** The reward cells are lit (a machine chip for reward volume is hovered). */
  litReward: boolean;
  /** A row to mark — the one a problem jump landed on. */
  activeRow: number | null;
  onHoverRow: (conditionId: string | null) => void;
  onChange: (next: TrialTypeDef[]) => void;
}) {
  const [hot, setHot] = useState<number | null>(null);
  // Two lines per row while every row fits that way in the room the panel has;
  // one line, with a shared caption below, once they would not. Measured, so
  // a tall window keeps the roomier form for more conditions.
  const body = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = body.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height;
      if (h !== undefined) setRoom(Math.round(h));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const comfortable =
    trials.length <= 2 || (room !== null && trials.length * COMFORTABLE_H <= room + COMPACT_H);
  const weights = readsWeights(mode);

  const responses = useMemo(() => channelsOf(rig, "response"), [rig]);
  const rewards = useMemo(() => channelsOf(rig, "reward"), [rig]);
  const servedWell = useMemo(() => {
    const out: Record<string, string | undefined> = {};
    for (const [name, channel] of Object.entries(rig?.channels ?? {})) {
      if (channel.kind === "reward") out[name] = channel.well;
    }
    return out;
  }, [rig]);

  const update = (index: number, patch: Partial<TrialTypeDef>) =>
    onChange(trials.map((t, i) => (i === index ? { ...t, ...patch } : t)));

  const remove = (index: number) => onChange(trials.filter((_, i) => i !== index));

  const add = () => {
    // Seeded from the LAST row, so a second condition is the cells that
    // differ — and onto the first free line, so it arrives presentable.
    const taken = new Set(trials.map((t) => t.odorChannel));
    const free = Object.entries(rig?.channels ?? {}).find(
      ([name, c]) => c.kind === "emitter" && !taken.has(name),
    )?.[0];
    const previous = trials[trials.length - 1];
    const base = previous ? { ...previous, label: "" } : blankTrial();
    onChange([
      ...trials,
      { ...base, odorChannel: free ?? "", onsetStrobe: free ? (declaredOnset(rig, free) ?? "") : "" },
    ]);
  };

  const grid = weights ? GRID_WEIGHTED : GRID;
  const tableProblems = diagnosticsAt(diagnostics, "trials").filter((d) => d.location === "trials");
  const foot = !comfortable && hot !== null ? trials[hot] : undefined;

  return (
    <Panel
      id="trials"
      name="Trial types"
      note={`${trials.length} condition${trials.length === 1 ? "" : "s"} · one odor line each`}
      className="flex-1"
      right={
        <button
          type="button"
          onClick={add}
          className="flex shrink-0 items-center gap-1 rounded-sm border border-halo px-2 py-0.5 text-[10px] text-static transition-colors hover:border-pulsar hover:text-starlight"
        >
          <Plus size={11} strokeWidth={1.75} />
          Trial type
        </button>
      }
    >
      <div className={`${grid} border-b border-halo/70 pb-1 font-mono text-[8.5px] tracking-[0.14em] text-static/60 uppercase`}>
        <span />
        <span>condition</span>
        <span>odor line</span>
        <span>answers at</span>
        <span>paid from</span>
        <span className="text-right">ms</span>
        {weights && <span className="text-right">weight</span>}
        <span />
        <span />
      </div>

      <div ref={body} className="scrollbar-slim -mx-1 min-h-0 flex-1 overflow-y-auto px-1 pt-1">
        {trials.length === 0 && (
          <p className="py-4 text-center text-[11px] text-static/70">
            No trial types yet — add one for each odor line this task presents.
          </p>
        )}
        <AnimatePresence initial={false}>
          {trials.map((trial, index) => {
            const problems = diagnosticsAt(diagnostics, `trials[${index}]`);
            const at = (field: string) =>
              problems.some((d) => d.location === `trials[${index}].${field}`);
            const condition = conditionOfRow(index);
            return (
              <motion.div
                // Index-keyed on purpose: row order IS identity (slot i is PW<i+1>).
                key={index}
                layout
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                transition={springSnappy}
                onPointerEnter={() => {
                  setHot(index);
                  onHoverRow(condition);
                }}
                onPointerLeave={() => {
                  setHot(null);
                  onHoverRow(null);
                }}
                onFocusCapture={() => {
                  setHot(index);
                  onHoverRow(condition);
                }}
                className={`group rounded-sm border-y px-1 transition-colors ${
                  activeRow === index
                    ? "border-pulsar/40 bg-pulsar/[0.07]"
                    : hot === index
                      ? "border-transparent bg-halo/20"
                      : "border-transparent"
                } ${comfortable ? "py-1.5" : "py-0.5"}`}
              >
                <div className={`${grid} items-center`}>
                  {/* The slot number in the condition's own colour — the
                      series slot its tick on the machine and its Analytics
                      curve wear. An error ring when the row has problems. */}
                  <span
                    className="flex size-[18px] items-center justify-center rounded-sm font-mono text-[9px] font-medium text-void"
                    style={{
                      background: colorForIndex(index),
                      boxShadow: problems.length > 0 ? "0 0 0 1.5px var(--color-status-error)" : undefined,
                    }}
                  >
                    {index + 1}
                  </span>
                  <input
                    value={trial.label}
                    onChange={(e) => update(index, { label: e.target.value })}
                    placeholder="name this condition"
                    aria-label={`Name for trial type ${index + 1}`}
                    aria-invalid={at("label")}
                    title="Your name for this condition — required. It titles the live sparkline, the learning curve and the strategy axis."
                    className={`min-w-0 rounded-sm border bg-transparent px-1.5 py-0.5 text-[12px] text-starlight transition-colors placeholder:text-static/40 focus:outline-none ${
                      at("label")
                        ? "border-status-error/60 focus:border-status-error"
                        : "border-transparent hover:border-halo focus:border-pulsar"
                    }`}
                  />
                  <Dropdown
                    value={trial.odorChannel}
                    options={lineOptions(rig, vocabulary, trials, index)}
                    placeholder="odor line…"
                    label={`Odor line for trial type ${index + 1}`}
                    invalid={at("odorChannel") || at("onsetStrobe")}
                    onChange={(line) =>
                      update(index, { odorChannel: line, onsetStrobe: declaredOnset(rig, line) ?? "" })
                    }
                  />
                  {trial.isGo ? (
                    <>
                      <Dropdown
                        value={trial.responseChannel ?? ""}
                        options={responses}
                        placeholder="port…"
                        label={`Response port for trial type ${index + 1}`}
                        invalid={at("responseChannel")}
                        onChange={(v) => update(index, { responseChannel: v || null })}
                      />
                      <Dropdown
                        value={trial.rewardChannel ?? ""}
                        options={rewards}
                        placeholder="line…"
                        label={`Reward line for trial type ${index + 1}`}
                        invalid={at("rewardChannel")}
                        onChange={(v) => update(index, { rewardChannel: v || null })}
                      />
                      <span className={`rounded-sm transition-shadow ${litReward ? "ring-1 ring-pulsar" : ""}`}>
                        <NumberInput
                          label={`Reward volume for trial type ${index + 1}`}
                          title="Solenoid open time when this condition is answered correctly — its reward volume."
                          value={trial.rewardTime}
                          fallback={100}
                          integer
                          min={0}
                          max={5000}
                          align="right"
                          invalid={at("rewardTime")}
                          className="w-full px-1.5 py-0.5 text-[11px]"
                          onChange={(rewardTime) => update(index, { rewardTime })}
                        />
                      </span>
                    </>
                  ) : (
                    <span className="col-span-3 truncate px-1 text-[10px] italic text-static/60">
                      correct answer is to withhold
                    </span>
                  )}
                  {weights && (
                    <NumberInput
                      label={`Weight for trial type ${index + 1}`}
                      title={
                        mode === "weighted"
                          ? "This type's share of the trials on its side — the sides stay balanced"
                          : "This type's share of the session"
                      }
                      value={trial.weight}
                      fallback={0}
                      integer
                      min={0}
                      max={100}
                      align="right"
                      className="w-full px-1.5 py-0.5 text-[11px]"
                      onChange={(weight) => update(index, { weight })}
                    />
                  )}
                  <GoToggle
                    on={trial.isGo}
                    onChange={(isGo) =>
                      update(index, {
                        isGo,
                        // A no-go type answers at no port and pays nothing;
                        // clearing both together is its definition.
                        ...(isGo ? {} : { responseChannel: null, rewardChannel: null }),
                      })
                    }
                  />
                  <button
                    type="button"
                    onClick={() => remove(index)}
                    aria-label={`Remove trial type ${index + 1}`}
                    className="text-static/30 transition-colors hover:text-status-error group-hover:text-static"
                  >
                    <Trash2 size={11} strokeWidth={1.75} />
                  </button>
                </div>

                {comfortable && (
                  <RowCaption
                    trial={trial}
                    index={index}
                    mode={mode}
                    rig={rig}
                    vocabulary={vocabulary}
                    servedWell={servedWell}
                    problems={problems}
                    onFix={(onset) => update(index, { onsetStrobe: onset })}
                  />
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* Compact rows keep their second line here, for the row under the
          pointer or focus — one fixed slot the eye learns. */}
      {!comfortable && (
        <div className="min-h-[18px] border-t border-halo/60 pt-1">
          {foot && hot !== null && (
            <RowCaption
              trial={foot}
              index={hot}
              mode={mode}
              rig={rig}
              vocabulary={vocabulary}
              servedWell={servedWell}
              problems={diagnosticsAt(diagnostics, `trials[${hot}]`)}
              onFix={(onset) => update(hot, { onsetStrobe: onset })}
            />
          )}
        </div>
      )}

      {tableProblems
        .filter((d) => d.code === "TSK108")
        .map((problem, i) => (
          <Problem key={i} diagnostic={problem} />
        ))}
    </Panel>
  );
}

const GRID =
  "grid grid-cols-[18px_minmax(0,1fr)_112px_84px_84px_46px_70px_12px] gap-x-1.5";
const GRID_WEIGHTED =
  "grid grid-cols-[18px_minmax(0,1fr)_112px_84px_84px_46px_40px_70px_12px] gap-x-1.5";

function channelsOf(rig: RigDocument | null, kind: string): DropdownOption[] {
  return Object.entries(rig?.channels ?? {})
    .filter(([, c]) => c.kind === kind)
    .map(([name]) => {
      const label = channelLabel(rig, name);
      const wire = name.replace(/_/g, " ");
      return { value: name, label, detail: label === wire ? undefined : wire };
    });
}

/**
 * A row's second line: its onset code (read-only — the line's own), then the
 * contingency in the rig's words, or the row's first problem.
 */
function RowCaption({
  trial,
  index,
  mode,
  rig,
  vocabulary,
  servedWell,
  problems,
  onFix,
}: {
  trial: TrialTypeDef;
  index: number;
  mode: SelectionMode;
  rig: RigDocument | null;
  vocabulary: StrobeVocabulary | null;
  servedWell: Record<string, string | undefined>;
  problems: TaskDiagnostic[];
  onFix: (onset: string) => void;
}) {
  const declared = trial.odorChannel ? declaredOnset(rig, trial.odorChannel) : null;
  const mismatch = declared !== null && trial.onsetStrobe !== "" && trial.onsetStrobe !== declared;
  const number = trial.onsetStrobe ? codeNumber(vocabulary, trial.onsetStrobe) : null;
  const first = problems.find((p) => p.code !== "TSK114");

  return (
    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 pl-[24px] text-[10px]">
      {trial.odorChannel && !declared && (
        <span className="font-mono text-status-warning">no onset declared — set it on the Rig tab</span>
      )}
      {trial.onsetStrobe && (
        <span
          className={`font-mono ${mismatch ? "text-status-error" : "text-static/70"}`}
          title="The code this condition's odor onset is recorded as — the line's own, from the Rig tab"
        >
          {trial.onsetStrobe}
          {number !== null && ` · ${number}`}
        </span>
      )}
      {mismatch && declared && (
        <>
          <button
            type="button"
            onClick={() => onFix(declared)}
            className="rounded-sm border border-status-error/50 px-1.5 font-mono text-status-error transition-colors hover:bg-status-error/10"
            title="If this bottle has always been recorded under the stored code, change the line's onset on the Rig tab instead, so past and future sessions agree."
          >
            use {declared}
          </button>
          <span className="text-static/60">or change the line on the Rig tab</span>
        </>
      )}
      {!mismatch && first ? (
        <span className="flex min-w-0 items-center gap-1 text-status-error">
          <TriangleAlert size={10} strokeWidth={1.75} className="shrink-0" />
          <span className="truncate" title={first.message}>
            <span className="font-mono opacity-70">{first.code}</span> {first.message}
          </span>
        </span>
      ) : (
        !mismatch && <Contingency trial={trial} rig={rig} servedWell={servedWell} />
      )}
      {!trial.isGo && !presentsNoGo(mode) && (
        <span className="text-status-warning">
          not presented under {modeInfo(mode).label.toLowerCase()} — only Pool presents no-go
        </span>
      )}
      <span className="sr-only">Trial type {index + 1}</span>
    </div>
  );
}

/**
 * Stimulus → answer → payment in the rig's own words. Worth its line because it
 * is what catches a reward line serving the wrong well BY EYE (TSK103).
 */
function Contingency({
  trial,
  rig,
  servedWell,
}: {
  trial: TrialTypeDef;
  rig: RigDocument | null;
  servedWell: Record<string, string | undefined>;
}) {
  if (!trial.odorChannel) return null;
  const odor = channelLabel(rig, trial.odorChannel);
  const arrow = <ArrowRight size={9} strokeWidth={1.75} className="shrink-0 text-static/50" />;
  if (!trial.isGo) {
    return (
      <span className="flex items-center gap-1 text-static/70">
        <Chip>{odor}</Chip>
        {arrow}
        <Chip>withhold</Chip>
      </span>
    );
  }
  if (!trial.responseChannel || !trial.rewardChannel) return null;
  const serves = servedWell[trial.rewardChannel];
  const wrong = serves !== undefined && serves !== trial.responseChannel;
  return (
    <span className="flex min-w-0 items-center gap-1 text-static/70">
      <Chip>{odor}</Chip>
      {arrow}
      <Chip>{channelLabel(rig, trial.responseChannel)}</Chip>
      <span className="text-static/50">paid from</span>
      <Chip error={wrong}>
        {channelLabel(rig, trial.rewardChannel)}
        {serves !== undefined && ` · plumbed to ${channelLabel(rig, serves)}`}
      </Chip>
    </span>
  );
}

function Chip({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return (
    <span
      className={`truncate rounded-full px-1.5 ${
        error ? "bg-status-error/15 text-status-error" : "bg-halo/40 text-starlight/90"
      }`}
    >
      {children}
    </span>
  );
}

/** A table-level problem, on one line — the full sentence is its tooltip and
 *  sits in the header's Problems list. */
function Problem({ diagnostic }: { diagnostic: TaskDiagnostic }) {
  return (
    <p className="mt-1 flex min-w-0 items-center gap-1.5 text-[10px] text-status-error" title={diagnostic.message}>
      <TriangleAlert size={11} strokeWidth={1.75} className="shrink-0" />
      <span className="truncate">
        <span className="font-mono opacity-70">{diagnostic.code}</span> {diagnostic.message}
      </span>
    </p>
  );
}

/** Go / no-go as a segmented pair, so it shows both states and marks one. */
function GoToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <span
      role="group"
      aria-label="Trial kind"
      title={on ? "A go trial: one port is correct" : "A no-go trial: withholding is correct"}
      className="flex overflow-hidden rounded-sm border border-halo"
    >
      {[true, false].map((value) => (
        <button
          key={String(value)}
          type="button"
          aria-pressed={on === value}
          onClick={() => onChange(value)}
          className={`flex-1 px-1 py-0.5 text-[9.5px] whitespace-nowrap transition-colors ${
            on === value ? "bg-pulsar/18 text-starlight" : "text-static hover:text-starlight"
          }`}
        >
          {value ? "go" : "no-go"}
        </button>
      ))}
    </span>
  );
}
