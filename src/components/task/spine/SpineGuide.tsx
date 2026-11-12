import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, PencilRuler } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button, NumberInput, TextInput } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { springPanel } from "@/lib/motion";
import { spinePalette } from "@/lib/taskdef/commands";
import {
  bindRole,
  GUIDE_STEPS,
  type GuideStep,
  nextStep,
  previousStep,
  setScope,
  STEP_WORDS,
  stepDiagnostics,
  stepIndex,
  stimulusRoles,
} from "@/lib/taskdef/guide";
import { setPhase, setRow, type SpineDefinition } from "@/lib/taskdef/spine";
import { slotTypeLabel } from "@/lib/taskdef/spineLabels";
import { everyLine } from "@/lib/taskdef/spineProblems";
import { channelChoices, channelGroups, roleScopes, sharedChannel, timingFields } from "@/lib/taskdef/spineWords";
import type { TaskDocument } from "@/lib/taskdef/types";
import type { TaskSession } from "@/lib/taskdef/useTask";
import { useSidecar } from "@/lib/ws/context";

import { ShapeControl } from "./BlockTimeline";
import { ChannelSelect, Note, ProblemLines } from "./bits";
import { NameInput, RowAnswers } from "./RowsTable";
import { SeedGrid } from "./SeedChooser";
import { SimulatePanel } from "./SimulatePanel";

/**
 * The guided first spine task (`TASKS.md#the-guide`): eight steps from a
 * paradigm to a saved task, for someone building their first.
 *
 * ONE DOCUMENT, THE EDITOR'S. The first step seeds the route's `useTask`
 * session; every later step edits that same unsaved document with the
 * editor's functions and controls, and every problem it shows is the
 * preview's, filed under the step that can fix it (`guide.stepDiagnostics`).
 * **Open in the editor** on any step leaves with everything kept.
 */
export function SpineGuide({
  session,
  rig,
  onPickSeed,
  onLeave,
  onSave,
}: {
  session: TaskSession;
  rig: RigDocument | null;
  onPickSeed: (definition: TaskDocument) => void;
  /** Drop into the editor with the document as it is (or the seed chooser, before a paradigm). */
  onLeave: () => void;
  onSave: () => void;
}) {
  const { client, status } = useSidecar();
  const [step, setStep] = useState<GuideStep>("paradigm");
  const [classes, setClasses] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const def = session.definition as SpineDefinition | null;
  const { setDefinition } = session;
  // The roles asked per trial type: the stimulus at first (`stimulusRoles`),
  // then whatever the user flips. Set once per paradigm.
  const [perType, setPerType] = useState<string[] | null>(null);

  useEffect(() => {
    if (status !== "connected") return;
    void spinePalette(client)
      .then((reply) => setClasses(reply.outcomeClasses))
      .catch((err) => setError(errorMessage(err)));
  }, [client, status]);

  useEffect(() => {
    if (def && perType === null) {
      const scopes = roleScopes(def);
      setPerType([...new Set([...stimulusRoles(def), ...def.slots.filter((s) => scopes[s.id] === "per-type").map((s) => s.id)])]);
    }
  }, [def, perType]);

  const diagnostics = useMemo(() => stepDiagnostics(step, session.diagnostics), [step, session.diagnostics]);
  const roles = perType ?? [];
  const shared = def ? def.slots.map((s) => s.id).filter((id) => !roles.includes(id)) : [];
  const lines = def ? everyLine(diagnostics, def, rig, shared) : [];
  const at = stepIndex(step);
  const next = nextStep(step);
  const previous = previousStep(step);
  const words = STEP_WORDS[step];

  const pickSeed = (seed: TaskDocument) => {
    setPerType(null);
    onPickSeed(seed);
    setStep("names");
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springPanel}
      className="scrollbar-none absolute inset-0 overflow-y-auto"
    >
      <section className="mx-auto flex max-w-4xl flex-col gap-4 px-10 py-9">
        <div className="flex items-center gap-3">
          <h1 className="font-display text-[22px] text-starlight">Your first task</h1>
          <span className="font-mono text-[10px] tracking-wide text-static/70 uppercase">
            step {at + 1} of {GUIDE_STEPS.length}
          </span>
          <span className="flex-1" />
          <Button variant="ghost" onClick={onLeave} title="Leave the guide; everything filled in so far is kept">
            <PencilRuler size={13} strokeWidth={1.75} />
            {def ? "Open in the editor" : "Skip the guide"}
          </Button>
        </div>

        <ol className="flex flex-wrap gap-x-1 gap-y-1" aria-label="Steps">
          {GUIDE_STEPS.map((s, i) => (
            <li key={s}>
              <button
                type="button"
                disabled={!def && s !== "paradigm"}
                aria-current={s === step ? "step" : undefined}
                onClick={() => setStep(s)}
                className={`rounded-sm border px-2 py-0.5 text-[10.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  s === step ? "border-pulsar/70 text-starlight" : "border-halo text-static hover:text-starlight"
                }`}
              >
                {i + 1}. {STEP_WORDS[s].title}
              </button>
            </li>
          ))}
        </ol>

        <div className="telemetry flex flex-col gap-3 px-5 py-4">
          <div>
            <h2 className="font-display text-[16px] text-starlight">{words.title}</h2>
            <p className="mt-1 max-w-prose text-[12px] leading-relaxed text-static">{words.help}</p>
          </div>
          {error && <p className="text-[11px] text-status-error">{error}</p>}

          {step === "paradigm" && <SeedGrid onPick={pickSeed} />}
          {def && step === "names" && (
            <div className="flex flex-col gap-2">
              {def.rows.map((row, r) => (
                <label key={row.id} className="flex items-center gap-3">
                  <span className="w-6 font-mono text-[10px] text-static">{r + 1}</span>
                  <NameInput
                    value={row.name}
                    invalid={diagnostics.some((d) => d.target.kind === "row" && d.target.index === r)}
                    onChange={(name) => setDefinition(setRow(def, r, { ...row, name }))}
                  />
                </label>
              ))}
              <Note>More trial types can be added in the editor.</Note>
            </div>
          )}
          {def && step === "roles" && (
            <RolesStep def={def} session={session} rig={rig} perType={roles} onPerType={setPerType} />
          )}
          {def && step === "answers" && (
            <div className="flex flex-col gap-3">
              {def.rows.map((row, r) => (
                <div key={row.id} className="flex flex-col gap-1">
                  <span className="text-[12px] text-starlight">{row.name || `Trial type ${r + 1}`}</span>
                  <div className="flex flex-col gap-1 pl-4">
                    <RowAnswers def={def} r={r} rig={rig} outcomeClasses={classes} diagnostics={session.diagnostics} onChange={setDefinition} />
                  </div>
                </div>
              ))}
            </div>
          )}
          {def && step === "timings" && (
            <div className="grid grid-cols-[auto_auto] items-center justify-start gap-x-4 gap-y-2">
              {timingFields(def).map((field) => {
                const phase = def.spine[field.at]!;
                return (
                  <label key={`${field.at}-${field.key}`} className="contents">
                    <span className="text-[12px] text-static">{field.label}</span>
                    <span className="flex items-center gap-1.5">
                      <NumberInput
                        value={phase[field.key]}
                        fallback={0}
                        integer
                        min={0}
                        label={field.label}
                        invalid={diagnostics.some((d) => d.target.kind === "phase" && d.target.index === field.at)}
                        className="w-[88px]"
                        onChange={(ms) => setDefinition(setPhase(def, field.at, { ...phase, [field.key]: ms }))}
                      />
                      <span className="text-[11px] text-static">ms</span>
                    </span>
                  </label>
                );
              })}
            </div>
          )}
          {def && step === "session" && <ShapeControl def={def} onChange={setDefinition} />}
          {def && step === "simulate" && <SimulatePanel definition={def} diagnostics={session.diagnostics} />}
          {def && step === "save" && (
            <div className="flex flex-col gap-2">
              <label className="flex items-center gap-3">
                <span className="text-[12px] text-static">Task name</span>
                <TextInput
                  value={def.name}
                  label="Task name"
                  placeholder="name this task"
                  className="w-[260px]"
                  onChange={(name) => setDefinition({ ...def, name })}
                />
              </label>
              {session.diagnostics.length > 0 && (
                <Note>
                  A task can be saved with problems, but it cannot be flashed until they are fixed. Each one says what to do.
                </Note>
              )}
            </div>
          )}

          {def && step !== "simulate" && <ProblemLines lines={lines} onFix={(apply) => setDefinition(apply(def))} />}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" disabled={!previous} onClick={() => previous && setStep(previous)}>
            <ArrowLeft size={13} strokeWidth={1.75} />
            Back
          </Button>
          <span className="flex-1" />
          {next ? (
            <Button variant="primary" disabled={!def} onClick={() => setStep(next)}>
              Next: {STEP_WORDS[next].title}
              <ArrowRight size={13} strokeWidth={1.75} />
            </Button>
          ) : (
            <Button variant="primary" disabled={!def || !def.name.trim() || session.saving} onClick={onSave}>
              <Check size={13} strokeWidth={1.75} />
              {session.saving ? "Saving…" : "Save the task"}
            </Button>
          )}
        </div>
      </section>
    </motion.div>
  );
}

/**
 * Each role once, by its channel on this rig, with the per-trial-type roles
 * (the stimulus, at first) chosen in every trial type. Either can be flipped.
 * The channels offered are the preview's for that role.
 */
function RolesStep({
  def,
  session,
  rig,
  perType,
  onPerType,
}: {
  def: SpineDefinition;
  session: TaskSession;
  rig: RigDocument | null;
  perType: readonly string[];
  onPerType: (roles: string[]) => void;
}) {
  const view = session.spine;
  const groupsOf = (s: number) =>
    channelGroups(channelChoices(view?.slots[s]?.id === def.slots[s]!.id ? view.slots[s]!.channels : [], rig));
  const flip = (role: string, wantPerType: boolean) => {
    const next = setScope(perType, def, role, wantPerType);
    onPerType(next.perType);
    if (next.def !== def) session.setDefinition(next.def);
  };
  return (
    <div className="flex flex-col gap-2.5">
      {def.slots.map((slot, s) => {
        const each = perType.includes(slot.id);
        return (
          <div key={slot.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="w-28 font-mono text-[11px] text-starlight/90">
              {slot.id} <span className="text-static/60">{slotTypeLabel(slot.type, slot.mode)}</span>
            </span>
            {each ? (
              def.rows.map((row, r) => (
                <label key={row.id} className="flex items-center gap-1.5">
                  <span className="text-[10.5px] text-static">{row.name || `Trial type ${r + 1}`}</span>
                  <ChannelSelect
                    value={row.bind[slot.id] ?? ""}
                    groups={groupsOf(s)}
                    label={`${slot.id} in ${row.name || `trial type ${r + 1}`}`}
                    className="w-[150px]"
                    onChange={(channel) => session.setDefinition(bindRole(def, slot.id, channel, r))}
                  />
                </label>
              ))
            ) : (
              <ChannelSelect
                value={sharedChannel(def, slot.id)}
                groups={groupsOf(s)}
                label={`${slot.id}, in every trial type`}
                className="w-[150px]"
                onChange={(channel) => session.setDefinition(bindRole(def, slot.id, channel, null))}
              />
            )}
            <button
              type="button"
              onClick={() => flip(slot.id, !each)}
              className="text-[10.5px] text-pulsar transition-colors hover:text-starlight"
            >
              {each ? "same in every trial type" : "one per trial type"}
            </button>
          </div>
        );
      })}
      <Note>
        The roles asked once are the same wire in every trial type. The stimulus is asked per trial type, so each trial type can present its own.
      </Note>
    </div>
  );
}
