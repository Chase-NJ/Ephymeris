import { motion } from "framer-motion";
import { FlaskConical } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EditorHeader, type EditorShared, type ProblemPlace } from "@/components/task/editor/EditorHeader";
import { Panel } from "@/components/task/editor/Panel";
import { errorMessage } from "@/lib/cohorts/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { spinePalette } from "@/lib/taskdef/commands";
import {
  foldStored,
  insertPhase,
  removePhase,
  type SpineDefinition,
  type SpinePhase,
} from "@/lib/taskdef/spine";
import { problemLines, targetLines } from "@/lib/taskdef/spineProblems";
import { useSidecar } from "@/lib/ws/context";
import type { TaskDiagnostic } from "@/lib/ws/protocol";

import { BlockTimeline } from "./BlockTimeline";
import { PhasePanel } from "./PhasePanel";
import { RamMeter } from "./RamMeter";
import { RowsTable } from "./RowsTable";
import { SimulatePanel } from "./SimulatePanel";
import { SpineDiagram } from "./SpineDiagram";
import { ProblemLines } from "./bits";

/** How long a row a jump landed on stays marked. */
const MARK_MS = 2400;

interface Palette {
  phases: string[];
  outcomeClasses: string[];
  selections: string[];
  timedPhases: string[];
  weightedSelections: string[];
}

/**
 * A phase-spine task, open (`TASKS.md#the-spine-editor`): the trial drawn
 * left to right in time with the selected step's fields and the RAM readout
 * under it, the trial types with their shared wiring and each one's
 * contingency map as sentences, the session's shape and blocks, and Simulate,
 * which the header's Simulate button jumps to. Each panel shows what the task
 * is and folds the rest: a step's unset fields sit in an Add menu, shared
 * roles are bound once, a block's fields open on a click.
 *
 * EVERY REDRAW COMES FROM `tasks.preview`. This holds the unsaved document
 * and applies the operator's edits to it (`lib/taskdef/spine.ts`); the diagram,
 * what each slot can bind, the block sequence, the meter and every problem are
 * the preview's answer for that document (`profile.spine`, `SpineView`,
 * `TaskDiagnostic.target`). The rig document is read for channel labels and
 * kinds only. A refused preview leaves the last good drawing, dimmed, with the
 * reason in the header.
 *
 * EACH PROBLEM IS SAID WHERE IT IS, AS AN INSTRUCTION: on its step and in its
 * fields, under its trial type and in its cell, on its block, under the meter,
 * each with a one-click fix where the document alone answers
 * (`lib/taskdef/spineProblems.ts`). Task-wide ones sit above the diagram. The
 * header's Problems list files them the same way, and a click selects the
 * step or block, or marks the trial type.
 */
export function SpineEditor({ shared, definition, rig }: { shared: EditorShared; definition: SpineDefinition; rig: RigDocument | null }) {
  const { session } = shared;
  const { setDefinition } = session;
  const { client, status } = useSidecar();
  const [palette, setPalette] = useState<Palette | null>(null);
  const [paletteError, setPaletteError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<number | null>(null);
  const [selectedBlock, setSelectedBlock] = useState<number | null>(null);
  const [markedRow, setMarkedRow] = useState<number | null>(null);
  const markTimer = useRef<number | undefined>(undefined);
  const spineRef = useRef<HTMLDivElement>(null);
  const blocksRef = useRef<HTMLDivElement>(null);
  const simulateRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => window.clearTimeout(markTimer.current), []);

  useEffect(() => {
    if (status !== "connected") return;
    void spinePalette(client)
      .then((reply) =>
        setPalette({
          phases: reply.phases,
          outcomeClasses: reply.outcomeClasses,
          selections: reply.selections,
          timedPhases: reply.timedPhases,
          weightedSelections: reply.weightedSelections,
        }),
      )
      .catch((err) => setPaletteError(errorMessage(err)));
  }, [client, status]);

  const diagnostics = session.diagnostics;
  const view = session.spine;
  const stored = view?.stored ?? [];

  /** The phases as the preview compiled them, never the document being typed. */
  const drawn = useMemo(() => {
    const snapshot = session.profile?.spine as { spine?: unknown } | undefined;
    return Array.isArray(snapshot?.spine) ? (snapshot.spine as SpinePhase[]) : [];
  }, [session.profile]);

  const clearStored = useCallback(
    (key: string) => {
      const params = { ...definition.params };
      delete params[key];
      setDefinition({ ...definition, params });
    },
    [definition, setDefinition],
  );

  const onJump = useCallback((d: TaskDiagnostic) => {
    const { kind, index } = d.target;
    if (kind === "phase" && index !== null) {
      setSelectedPhase(index);
      spineRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else if (kind === "row" && index !== null) {
      setMarkedRow(index);
      window.clearTimeout(markTimer.current);
      markTimer.current = window.setTimeout(() => setMarkedRow(null), MARK_MS);
      document.getElementById(`spine-row-${index}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    } else if (kind === "block" && index !== null) {
      setSelectedBlock(index);
      blocksRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else if (kind === "session") {
      blocksRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else if (kind === "ram") {
      spineRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, []);

  /** The task-wide lines: every missing edge code as one, and anything about the task as a whole. */
  const taskWide = useMemo(
    () => problemLines(diagnostics, definition, rig, null).filter((l) => l.code === "SPN103" || l.diagnostics[0]?.target.kind !== "row"),
    [diagnostics, definition, rig],
  );

  const phase = selectedPhase !== null && selectedPhase < definition.spine.length ? selectedPhase : null;
  const problems = diagnostics.length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springPanel}
      className="scrollbar-none absolute inset-0 flex flex-col gap-3 overflow-y-auto px-4 py-4"
    >
      <EditorHeader
        session={session}
        saved={shared.saved}
        diagnostics={diagnostics}
        categories={shared.categories}
        detailsOpen={shared.detailsOpen}
        onDetailsOpen={shared.onDetailsOpen}
        problemsOpen={shared.problemsOpen}
        onProblemsOpen={shared.onProblemsOpen}
        onJump={onJump}
        placeOf={(d) => placeOf(d, definition)}
        actions={
          <button
            type="button"
            onClick={() => simulateRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
            title={problems ? `Simulate runs once the task's ${problems} problem${problems === 1 ? " is" : "s are"} fixed` : "Check the task against a pretend animal before anything is flashed"}
            className="flex items-center gap-1 rounded-sm border border-halo px-2 py-1 text-[11px] text-static transition-colors hover:border-pulsar/70 hover:text-starlight"
          >
            <FlaskConical size={12} strokeWidth={1.75} />
            Simulate
          </button>
        }
        onBack={shared.onBack}
        onSave={shared.onSave}
      />
      {shared.listError && <p className="text-[11px] text-status-error">{shared.listError}</p>}
      {paletteError && <p className="text-[11px] text-status-error">{paletteError}</p>}
      <ProblemLines lines={taskWide} onFix={(apply) => setDefinition(apply(definition))} />

      <motion.div variants={CASCADE} initial="hidden" animate="shown" className="flex flex-col gap-3 pb-4">
        <motion.div variants={RISE} ref={spineRef}>
            <Panel
              id="spine"
              name="Trial"
              note={`${drawn.length} step${drawn.length === 1 ? "" : "s"} · left to right in time · click a step to edit it`}
            >
              <SpineDiagram
                phases={drawn}
                kinds={palette?.phases ?? []}
                diagnostics={diagnostics}
                selected={phase}
                stale={session.stale}
                onSelect={(i) => setSelectedPhase(phase === i ? null : i)}
                onInsert={(at, kind) => {
                  // A stored value keyed by a phase index folds into its field
                  // first, so it moves with its phase (`foldStored`).
                  setDefinition(insertPhase(foldStored(definition, stored), at, kind, palette?.timedPhases ?? []));
                  setSelectedPhase(at);
                }}
              />
              {phase !== null && (
                <PhasePanel
                  def={definition}
                  at={phase}
                  diagnostics={diagnostics}
                  stored={stored}
                  onChange={setDefinition}
                  onRemove={() => {
                    setDefinition(removePhase(foldStored(definition, stored), phase));
                    setSelectedPhase(null);
                  }}
                  onClearStored={clearStored}
                />
              )}
              <RamMeter ram={view?.ram ?? null} lines={targetLines(diagnostics, definition, "ram", null)} onFix={(apply) => setDefinition(apply(definition))} />
            </Panel>
        </motion.div>

        <motion.div variants={RISE}>
          <Panel
            id="rows"
            name="Trial types"
            note={`${definition.rows.length} · wiring once, then what each presents and what every answer means`}
          >
            <RowsTable
              def={definition}
              view={view}
              rig={rig}
              outcomeClasses={palette?.outcomeClasses ?? []}
              diagnostics={diagnostics}
              stored={stored}
              marked={markedRow}
              onChange={setDefinition}
              onClearStored={clearStored}
            />
          </Panel>
        </motion.div>

        <motion.div variants={RISE} ref={blocksRef}>
          <Panel id="blocks" name="Session" note="its shape, and the blocks in the order they run">
            <BlockTimeline
              def={definition}
              view={view}
              selections={palette?.selections ?? []}
              weightedSelections={palette?.weightedSelections ?? []}
              outcomeClasses={palette?.outcomeClasses ?? []}
              diagnostics={diagnostics}
              stored={stored}
              selected={selectedBlock}
              onSelect={(b) => setSelectedBlock(selectedBlock === b ? null : b)}
              onChange={setDefinition}
              onClearStored={clearStored}
            />
          </Panel>
        </motion.div>

        <motion.div variants={RISE} ref={simulateRef} className="scroll-mt-4">
          <Panel id="simulate" name="Simulate" note="check it before an animal sees it: a session against a pretend animal, nothing flashed">
            <SimulatePanel definition={definition} diagnostics={diagnostics} />
          </Panel>
        </motion.div>
      </motion.div>
    </motion.div>
  );
}

/** Where the header's Problems list files a spine diagnostic: by its target. */
function placeOf(d: TaskDiagnostic, def: SpineDefinition): ProblemPlace {
  const { kind, index } = d.target;
  switch (kind) {
    case "phase":
      return { section: "Trial", which: index === null ? null : `step ${index + 1}` };
    case "row": {
      if (index === null) return { section: "Trial types", which: null };
      const name = def.rows[index]?.name;
      return { section: "Trial types", which: name || `trial type ${index + 1}` };
    }
    case "block":
      return { section: "Session", which: index === null ? null : `block ${index + 1}` };
    case "session":
      return { section: "Session", which: "session cap" };
    case "slot":
      return { section: "Roles", which: index === null ? null : (def.slots[index]?.id ?? null) };
    case "ram":
      return { section: "RAM", which: null };
    default:
      return { section: "Task", which: null };
  }
}
