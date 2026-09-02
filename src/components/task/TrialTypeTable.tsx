import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Layers, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import type { ReactNode } from "react";

import { Dropdown, type DropdownOption } from "@/components/common/Dropdown";
import { NumberInput, Segmented } from "@/components/common/controls";
import { colorForIndex } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import { blankTrial, channelLabel, diagnosticsAt } from "@/lib/taskdef/types";
import type { SelectionMode, TaskDiagnostic, TrialTypeDef } from "@/lib/taskdef/types";
import type { RigDocument } from "@/lib/hardware/types";
import type { StrobeVocabulary } from "@/lib/ws/protocol";

/**
 * The trial table — which odor means which answer, and what pays for it.
 *
 * THE SCREEN THIS WHOLE SYSTEM EXISTS FOR. "Odor 1 is go-right here and go-left
 * on the bench next door" used to be a firmware edit; it is a dropdown now.
 *
 * Each type is a CARD rather than a divider row: the row's five bindings are
 * captioned fields, so the form reads without its placeholders, and the
 * contingency renders under them as a chip sentence — stimulus → answer →
 * payment, in the rig's own words. The pickers are the themed `Dropdown`, whose
 * `detail` slot carries the second name a binding has (the wire name behind a
 * rig label, the number behind a strobe code) — the two kinds of name shown
 * together instead of one hiding the other.
 *
 * EVERY CELL IS A CHANNEL NAME, never a pin and never an index. The rig's
 * wiring supplies the options, so a channel that was renamed or removed shows
 * as a diagnostic against the row that binds it rather than as a task that
 * compiles and drives nothing. Same for the onset code: it is a name from the
 * vocabulary, because the codes are not contiguous and nothing may compute one.
 *
 * ROW ORDER IS THE CONTRACT. Slot i is pool weight PW<i+1> is `kTrials[i]` in
 * the generated firmware, so reordering re-weights a pool task — which is why
 * there is no drag handle here, and why the weight column lives ON the row
 * rather than in the parameter rail where it would outlive the row it
 * describes.
 *
 * TWO KINDS OF NAME, and keeping them apart is the point.
 *
 *   the RIG'S channel label   what this bench calls the line — "sandalwood".
 *                             Set on the Rig tab, follows the wiring, free to
 *                             rename, and everything on this screen reads it
 *                             back. It never enters the recorded profile.
 *   the ROW'S own label       the operator's name for the CONDITION. It does
 *                             enter the profile and the chart titles, so it is
 *                             part of the task's record and changing it is a
 *                             task edit.
 *
 * A new row arrives with an empty label for that reason: "odor 1 (sandalwood)"
 * was a claim about one bench's bottles baked into a shipped constant, which is
 * exactly what this table exists to stop. Empty is a starting point, not a
 * finished row — REQUIRED (TSK110), because the name is the only handle every
 * readout downstream has on the condition: the live sparkline, the learning
 * curve and a strategy axis are all titled from it, and a nameless one is read
 * back as whichever channel happened to carry it. TSK111 refuses two rows
 * under one name for the same reason TSK105 refuses two under one onset code.
 */
export function TrialTypeTable({
  trials,
  mode,
  rig,
  vocabulary,
  diagnostics,
  onChange,
  onModeChange,
}: {
  trials: TrialTypeDef[];
  mode: SelectionMode;
  rig: RigDocument | null;
  vocabulary: StrobeVocabulary | null;
  diagnostics: TaskDiagnostic[];
  onChange: (next: TrialTypeDef[]) => void;
  /**
   * How the next trial is chosen. It lives on THIS header rather than in a
   * details panel because the choice is visible here and nowhere else: pool
   * mode grows a weight column on every row, and anti-bias hides it. Until the
   * presets were retired the mode arrived pre-set and had no editor at all,
   * which made a pool task unbuildable from scratch.
   */
  onModeChange: (next: SelectionMode) => void;
}) {
  /**
   * Channels by kind, in DOCUMENT order — the order the firmware indexes.
   * Each option's `detail` is the channel name whenever the rig's label has
   * replaced it, so "sandalwood" still says which line it is.
   */
  const channels = useMemo(() => {
    const entries = Object.entries(rig?.channels ?? {});
    const of = (kind: string): DropdownOption[] =>
      entries
        .filter(([, c]) => c.kind === kind)
        .map(([name]) => {
          const label = channelLabel(rig, name);
          const wire = name.replace(/_/g, " ");
          return { value: name, label, detail: label === wire ? undefined : wire };
        });
    return { emitter: of("emitter"), response: of("response"), reward: of("reward") };
  }, [rig]);

  /** Which well each reward line is plumbed to — the TSK103 sentence needs it. */
  const servedWell = useMemo(() => {
    const out: Record<string, string | undefined> = {};
    for (const [name, channel] of Object.entries(rig?.channels ?? {})) {
      if (channel.kind === "reward") out[name] = channel.well;
    }
    return out;
  }, [rig]);

  /**
   * The codes that can announce a STIMULUS.
   *
   * A NUMBERED line turning on — `ODOR_3_ON`, and a hypothetical `TONE_2_ON`
   * on a box with speakers. Matching a bare `_ON` suffix offered `LIGHTS_ON`,
   * which is the trial-availability cue the runner emits on every trial: a task
   * that picked it would announce two conditions with one code and pool them in
   * every analysis, silently. The shape rule rather than a hardcoded `ODOR_`
   * prefix, because a stimulus is an emitter channel and nothing more — the
   * substrate is not this screen's business.
   *
   * The `detail` is the code NUMBER — the thing the recorded file actually
   * carries, worth seeing while choosing because the numbers are not
   * contiguous (110–113 are retired) and nothing may compute one.
   */
  const onsetOptions = useMemo(
    () =>
      (vocabulary?.codes ?? [])
        .filter((c) => /_\d+_ON$/.test(c.name))
        .map((c) => ({
          value: c.name,
          // NOT a rig label: a strobe code is a fact about the recorded
          // archive, not about what is in the bottle, and its name is the
          // thing an analysis will match on.
          label: c.name.replace(/_/g, " "),
          detail: String(c.code),
        })),
    [vocabulary],
  );

  const update = (index: number, patch: Partial<TrialTypeDef>) => {
    const next = trials.map((t, i) => (i === index ? { ...t, ...patch } : t));
    onChange(next);
  };

  const remove = (index: number) => onChange(trials.filter((_, i) => i !== index));

  const add = () => {
    // Seeded from the LAST row rather than from nothing, so adding a second
    // condition to a working task means changing the two cells that differ.
    // Never from a defaults table: a row that arrived with an odor nobody
    // picked reads as deliberate.
    const previous = trials[trials.length - 1];
    const seed = previous
      ? { ...previous, label: "", onsetStrobe: "", odorChannel: "" }
      : blankTrial();
    onChange([...trials, seed]);
  };

  return (
    <div className="hud flex min-h-0 flex-col rounded-md">
      <header className="flex items-center justify-between gap-3 border-b border-halo px-3.5 py-2.5">
        <Layers size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-starlight">Trial types</div>
          <div className="mt-0.5 text-[10px] text-static/70">
            {mode === "pool"
              ? "Presented from a weighted, block-shuffled pool."
              : "Presented by anti-bias selection: a side is drawn against the animal's recent bias, then a type from that side."}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Segmented<SelectionMode>
            label="How the next trial is chosen"
            value={mode}
            options={[
              { value: "antibias", label: "Anti-bias" },
              { value: "pool", label: "Pool" },
            ]}
            onChange={onModeChange}
          />
          <button
            type="button"
            onClick={add}
            className="flex shrink-0 items-center gap-1 rounded-md border border-halo px-2.5 py-1 text-[10px] text-static transition-colors hover:border-pulsar hover:text-starlight"
          >
            <Plus size={11} strokeWidth={1.75} />
            Add trial type
          </button>
        </div>
      </header>

      <div className="scrollbar-none flex min-h-0 flex-col gap-2 overflow-y-auto p-2.5">
        {trials.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-6">
            <p className="text-[11px] text-static/70">
              No trial types yet. A task needs at least one.
            </p>
            <button
              type="button"
              onClick={add}
              className="flex items-center gap-1 rounded-md border border-halo px-2.5 py-1 text-[10px] text-static transition-colors hover:border-pulsar hover:text-starlight"
            >
              <Plus size={11} strokeWidth={1.75} />
              Add the first one
            </button>
          </div>
        )}

        <AnimatePresence initial={false}>
          {trials.map((trial, index) => {
            const rowProblems = diagnosticsAt(diagnostics, `trials[${index}]`);
            const problemAt = (field: string) =>
              rowProblems.some((d) => d.location === `trials[${index}].${field}`);
            return (
              <motion.div
                // Index-keyed on purpose: row order IS identity here (slot i is
                // PW<i+1>), and there is no reorder to track.
                key={index}
                layout
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                transition={springSnappy}
                className="group rounded-md border border-halo/60 bg-nebula/30 px-3 py-2.5"
              >
                <div className="mb-2 flex items-center gap-2">
                  {/* The slot number in the condition's own colour — the series
                      slot its glyph node, its state-machine tick and its
                      Analytics curve all wear. One colour per condition,
                      everywhere the condition appears. */}
                  <span
                    className="flex size-[18px] shrink-0 items-center justify-center rounded-sm font-mono text-[9px] font-medium text-void"
                    style={{ background: colorForIndex(index) }}
                  >
                    {index + 1}
                  </span>
                  <input
                    value={trial.label}
                    onChange={(e) => update(index, { label: e.target.value })}
                    placeholder="name this condition"
                    aria-label={`Name for trial type ${index + 1}`}
                    aria-invalid={problemAt("label")}
                    title={
                      "Your name for this condition — required. It reaches the " +
                      "recorded profile and titles the live sparkline, the " +
                      "learning curve and the strategy axis, so it is how every " +
                      "readout refers to this trial type. This is deliberately " +
                      "NOT the rig's channel label: that follows the wiring and " +
                      "is free to rename, while this is part of the task's record."
                    }
                    className={`min-w-0 flex-1 rounded-sm border bg-transparent px-1.5 py-0.5 text-[11px] text-starlight transition-colors placeholder:text-static/40 focus:outline-none ${
                      problemAt("label")
                        ? "border-status-error/60 focus:border-status-error"
                        : "border-transparent hover:border-halo focus:border-pulsar"
                    }`}
                  />
                  <GoToggle
                    on={trial.isGo}
                    onChange={(isGo) =>
                      update(index, {
                        isGo,
                        // A no-go type answers at no port and pays nothing; both
                        // being absent IS the definition of it, so clearing them
                        // together is the only consistent state.
                        ...(isGo ? {} : { responseChannel: null, rewardChannel: null }),
                      })
                    }
                  />
                  <button
                    type="button"
                    onClick={() => remove(index)}
                    title="Remove this trial type"
                    className="shrink-0 text-static/40 transition-colors hover:text-status-error group-hover:text-static"
                  >
                    <Trash2 size={12} strokeWidth={1.75} />
                  </button>
                </div>

                <div
                  className={`grid items-end gap-2 ${
                    mode === "pool"
                      ? "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_3.25rem]"
                      : "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]"
                  }`}
                >
                  <Field caption="odor line">
                    <Dropdown
                      value={trial.odorChannel}
                      options={channels.emitter}
                      placeholder="choose…"
                      label={`Odor line for trial type ${index + 1}`}
                      invalid={problemAt("odorChannel")}
                      onChange={(v) => update(index, { odorChannel: v })}
                    />
                  </Field>
                  <Field caption="onset code">
                    <Dropdown
                      value={trial.onsetStrobe}
                      options={onsetOptions}
                      placeholder="choose…"
                      label={`Onset code for trial type ${index + 1}`}
                      invalid={problemAt("onsetStrobe")}
                      onChange={(v) => update(index, { onsetStrobe: v })}
                    />
                  </Field>
                  {trial.isGo ? (
                    <>
                      <Field caption="answers at">
                        <Dropdown
                          value={trial.responseChannel ?? ""}
                          options={channels.response}
                          placeholder="choose…"
                          label={`Response port for trial type ${index + 1}`}
                          invalid={problemAt("responseChannel")}
                          onChange={(v) => update(index, { responseChannel: v || null })}
                        />
                      </Field>
                      <Field caption="paid from">
                        <Dropdown
                          value={trial.rewardChannel ?? ""}
                          options={channels.reward}
                          placeholder="choose…"
                          label={`Reward line for trial type ${index + 1}`}
                          invalid={problemAt("rewardChannel")}
                          onChange={(v) => update(index, { rewardChannel: v || null })}
                        />
                      </Field>
                    </>
                  ) : (
                    <div className="col-span-2 flex h-[26px] items-center px-1 text-[10px] italic text-static/60">
                      correct answer is to withhold
                    </div>
                  )}
                  {mode === "pool" && (
                    <Field caption="weight">
                      <NumberInput
                        label={`Weight for trial type ${index + 1}`}
                        title="Relative share of trials presenting this type"
                        value={trial.weight}
                        // Clearing the box means "never present this type", and 0 is
                        // the honest reading of an empty weight. Nothing merges
                        // underneath a weight the way a parameter has a default to
                        // fall back to — the row is the only declaration there is.
                        fallback={0}
                        integer
                        min={0}
                        max={100}
                        align="right"
                        className="w-full px-2 py-1 text-[11px]"
                        onChange={(weight) => update(index, { weight })}
                      />
                    </Field>
                  )}
                </div>

                <Contingency trial={trial} rig={rig} servedWell={servedWell} />

                {rowProblems.map((problem, i) => (
                  <p
                    key={i}
                    className="mt-1.5 flex items-start gap-1.5 text-[10px] text-status-error"
                  >
                    <TriangleAlert size={11} strokeWidth={1.75} className="mt-px shrink-0" />
                    <span>
                      <span className="font-mono opacity-70">{problem.code}</span>{" "}
                      {problem.message}
                    </span>
                  </p>
                ))}
              </motion.div>
            );
          })}
        </AnimatePresence>

        {/* Problems with the TABLE rather than with a row — an all-zero pool
            (TSK109), a table nothing can present (TSK108). Neither belongs
            against a single row, and without this slot they had nowhere to
            land at all: the empty-table case renders no rows to hang a message
            on. `StageRamp` carries the same footer for the same reason. */}
        {diagnosticsAt(diagnostics, "trials").map((problem, i) => (
          <p
            key={i}
            className="flex items-start gap-1.5 px-1 py-1 text-[10px] text-status-error"
          >
            <TriangleAlert size={11} strokeWidth={1.75} className="mt-px shrink-0" />
            <span>
              <span className="font-mono opacity-70">{problem.code}</span>{" "}
              {problem.message}
            </span>
          </p>
        ))}
      </div>
    </div>
  );
}

/** A captioned control — the tiny label that lets the row read without its
 *  placeholders. */
function Field({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="px-0.5 text-[9px] uppercase tracking-wider text-static/60">
        {caption}
      </span>
      {children}
    </label>
  );
}

/**
 * The row in a sentence — stimulus → answer → payment as chips, in the rig's
 * own words.
 *
 * Worth its own line because it is what catches a reward line serving the wrong
 * well BY EYE. The dropdowns say `fluid_2`; this says "plumbed to the right
 * well", which is readable next to "answered at the left well".
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
  // Every name here is the RIG'S, so the sentence reads in whatever the lab
  // actually put in the bottles: "sandalwood → right well" on one bench and
  // "orange → right well" on the next, from one component.
  const odor = channelLabel(rig, trial.odorChannel);
  const arrow = (
    <ArrowRight size={10} strokeWidth={1.75} className="shrink-0 text-static/50" />
  );
  if (!trial.isGo) {
    return (
      <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-static/70">
        <Chip>{odor}</Chip>
        {arrow}
        <Chip>withhold a response</Chip>
      </p>
    );
  }
  if (!trial.responseChannel || !trial.rewardChannel) return null;
  const serves = servedWell[trial.rewardChannel];
  const mismatch = serves !== undefined && serves !== trial.responseChannel;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-static/70">
      <Chip>{odor}</Chip>
      {arrow}
      <Chip>{channelLabel(rig, trial.responseChannel)}</Chip>
      <span className="text-static/50">paid from</span>
      <Chip error={mismatch}>
        {channelLabel(rig, trial.rewardChannel)}
        {serves !== undefined && ` · plumbed to ${channelLabel(rig, serves)}`}
      </Chip>
    </p>
  );
}

function Chip({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 ${
        error ? "bg-status-error/15 text-status-error" : "bg-halo/40 text-starlight/90"
      }`}
    >
      {children}
    </span>
  );
}

/**
 * Go / no-go as a segmented pair rather than one toggling button. The old
 * control showed a single word, and whether it named the current state or the
 * state a click would produce was anyone's guess — a segmented pair shows both
 * and marks one.
 */
function GoToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <span
      role="group"
      aria-label="Trial kind"
      title={on ? "A go trial: one port is correct" : "A no-go trial: withholding is correct"}
      className="flex shrink-0 overflow-hidden rounded-sm border border-halo"
    >
      <button
        type="button"
        aria-pressed={on}
        onClick={() => onChange(true)}
        className={`px-2 py-0.5 text-[10px] transition-colors ${
          on ? "bg-pulsar/18 text-starlight" : "text-static hover:text-starlight"
        }`}
      >
        go
      </button>
      <button
        type="button"
        aria-pressed={!on}
        onClick={() => onChange(false)}
        className={`px-2 py-0.5 text-[10px] transition-colors ${
          !on ? "bg-pulsar/18 text-starlight" : "text-static hover:text-starlight"
        }`}
      >
        no-go
      </button>
    </span>
  );
}
