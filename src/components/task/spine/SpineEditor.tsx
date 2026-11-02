import { motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EditorHeader, type EditorShared, type ProblemPlace } from "@/components/task/editor/EditorHeader";
import { Panel } from "@/components/task/editor/Panel";
import { errorMessage } from "@/lib/cohorts/commands";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { spinePalette } from "@/lib/taskdef/commands";
import {
  foldStored,
  insertPhase,
  removePhase,
  type SpineDefinition,
  type SpinePhase,
} from "@/lib/taskdef/spine";
import { useSidecar } from "@/lib/ws/context";
import type { TaskDiagnostic } from "@/lib/ws/protocol";

import { BlockTimeline } from "./BlockTimeline";
import { PhasePanel } from "./PhasePanel";
import { RamMeter } from "./RamMeter";
import { RowsTable } from "./RowsTable";
import { SpineDiagram } from "./SpineDiagram";
import { ProblemLines } from "./bits";

/** How long a row a jump landed on stays marked. */
const MARK_MS = 2400;

interface Palette {
  phases: string[];
  outcomeClasses: string[];
  selections: string[];
}

/**
 * A phase-spine task, open (`TASKS.md#the-spine-editor`): the spine drawn left
 * to right in time with the selected phase's fields under it, the RAM meter
 * beside it, the rows table with each row's contingency map, and the block
 * timeline.
 *
 * EVERY REDRAW COMES FROM `tasks.preview`. This holds the unsaved document
 * and applies the operator's edits to it (`lib/taskdef/spine.ts`); the diagram,
 * what each slot can bind, the block sequence, the meter and every problem are
 * the preview's answer for that document (`profile.spine`, `SpineView`,
 * `TaskDiagnostic.target`). A refused preview leaves the last good drawing,
 * dimmed, with the reason in the header.
 *
 * EACH PROBLEM IS SAID WHERE IT IS: on its phase node and in its fields, under
 * its row and in its cell, on its block, under the meter. Task-wide ones sit
 * above the diagram. The header's Problems list files them the same way, and a
 * click selects the phase or block, or marks the row.
 */
export function SpineEditor({ shared, definition }: { shared: EditorShared; definition: SpineDefinition }) {
  const { session } = shared;
  const { setDefinition } = session;
  const { client, status } = useSidecar();
  const [palette, setPalette] = useState<Palette | null>(null);
  const [paletteError, setPaletteError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<number | null>(null);
  const [selectedBlock, setSelectedBlock] = useState<number | null>(0);
  const [markedRow, setMarkedRow] = useState<number | null>(null);
  const markTimer = useRef<number | undefined>(undefined);
  const spineRef = useRef<HTMLDivElement>(null);
  const blocksRef = useRef<HTMLDivElement>(null);
  const ramRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => window.clearTimeout(markTimer.current), []);

  useEffect(() => {
    if (status !== "connected") return;
    void spinePalette(client)
      .then((reply) => setPalette({ phases: reply.phases, outcomeClasses: reply.outcomeClasses, selections: reply.selections }))
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
      ramRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, []);

  const taskWide = useMemo(
    () => diagnostics.filter((d) => d.target.kind === "task" || d.target.kind === "vocabulary"),
    [diagnostics],
  );

  const phase = selectedPhase !== null && selectedPhase < definition.spine.length ? selectedPhase : null;

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
        onBack={shared.onBack}
        onSave={shared.onSave}
      />
      {shared.listError && <p className="text-[11px] text-status-error">{shared.listError}</p>}
      {paletteError && <p className="text-[11px] text-status-error">{paletteError}</p>}
      <ProblemLines diagnostics={taskWide} />

      <motion.div variants={CASCADE} initial="hidden" animate="shown" className="flex flex-col gap-3 pb-4">
        <motion.div variants={RISE} className="flex items-start gap-3">
          <div ref={spineRef} className="min-w-0 flex-1">
            <Panel
              id="spine"
              name="Spine"
              note={`${drawn.length} phase${drawn.length === 1 ? "" : "s"} · left to right in time · click one to edit it`}
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
                  setDefinition(insertPhase(foldStored(definition, stored), at, kind));
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
            </Panel>
          </div>
          <div ref={ramRef} className="w-[250px] shrink-0">
            <Panel id="ram" name="RAM" note="the task's data, of the board's budget">
              <RamMeter ram={view?.ram ?? null} diagnostics={diagnostics} />
            </Panel>
          </div>
        </motion.div>

        <motion.div variants={RISE}>
          <Panel
            id="rows"
            name="Rows"
            note={`${definition.rows.length} trial type${definition.rows.length === 1 ? "" : "s"} · a channel for each slot, and where each response goes`}
          >
            <RowsTable
              def={definition}
              view={view}
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
          <Panel id="blocks" name="Blocks" note="the session, in the order its blocks run">
            <BlockTimeline
              def={definition}
              view={view}
              selections={palette?.selections ?? []}
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
      </motion.div>
    </motion.div>
  );
}

/** Where the header's Problems list files a spine diagnostic: by its target. */
function placeOf(d: TaskDiagnostic, def: SpineDefinition): ProblemPlace {
  const { kind, index } = d.target;
  switch (kind) {
    case "phase":
      return { section: "Spine", which: index === null ? null : `phase ${index + 1}` };
    case "row": {
      if (index === null) return { section: "Rows", which: null };
      const name = def.rows[index]?.name;
      return { section: "Rows", which: name || `row ${index + 1}` };
    }
    case "block":
      return { section: "Blocks", which: index === null ? null : (def.blocks[index]?.id ?? `block ${index + 1}`) };
    case "session":
      return { section: "Blocks", which: "session cap" };
    case "slot":
      return { section: "Slots", which: index === null ? null : (def.slots[index]?.id ?? null) };
    case "ram":
      return { section: "RAM", which: null };
    default:
      return { section: "Task", which: null };
  }
}
