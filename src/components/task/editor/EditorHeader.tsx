import { motion } from "framer-motion";
import { ArrowLeft, CircleAlert, FolderTree, TriangleAlert } from "lucide-react";

import { Button } from "@/components/common/controls";
import { TaskDetailsBody, detailsSummary } from "@/components/task/TaskDetails";
import { TaskGlyph } from "@/components/task/TaskGlyph";
import type { TaskDefinition, TaskDiagnostic } from "@/lib/taskdef/types";
import type { useTask } from "@/lib/taskdef/useTask";

import { Popover } from "./Popover";

/** Where a diagnostic lives on the page, for the Problems list and its jump. */
export type ProblemHome =
  | { kind: "row"; row: number }
  | { kind: "generation" }
  | { kind: "holds" }
  | { kind: "task" };

export function homeOf(diagnostic: TaskDiagnostic): ProblemHome {
  const row = /^trials\[(\d+)\]/.exec(diagnostic.location);
  if (row) return { kind: "row", row: Number(row[1]) };
  if (diagnostic.location === "trials") return { kind: "generation" };
  if (diagnostic.location.startsWith("stages")) return { kind: "holds" };
  return { kind: "task" };
}

/**
 * The editor's header: the way back, the task's mark and name, and the three
 * things that are about the whole task — its problems, its `START` line, its
 * details — then Revert and Save.
 */
export function EditorHeader({
  session,
  saved,
  diagnostics,
  categories,
  detailsOpen,
  onDetailsOpen,
  problemsOpen,
  onProblemsOpen,
  onJump,
  onBack,
  onSave,
}: {
  session: ReturnType<typeof useTask>;
  /** Whether this task exists on disk — the readout says "unsaved" if not. */
  saved: boolean;
  /** Server diagnostics plus the editor's own (TSK112). */
  diagnostics: TaskDiagnostic[];
  categories: readonly string[];
  detailsOpen: boolean;
  onDetailsOpen: (open: boolean) => void;
  problemsOpen: boolean;
  onProblemsOpen: (open: boolean) => void;
  onJump: (diagnostic: TaskDiagnostic) => void;
  onBack: () => void;
  onSave: () => void;
}) {
  const { definition, setDefinition } = session;
  if (!definition) return null;
  const problems = diagnostics.length;

  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2">
      <Button variant="ghost" onClick={onBack} title="Back to the task library">
        <ArrowLeft size={13} strokeWidth={1.75} />
      </Button>

      {/* The shared element from the landing's row: the mark the eye picked
          out of the list is still on screen after the route changes. */}
      <motion.span layoutId={`task-glyph-${definition.id}`} className="flex shrink-0">
        <TaskGlyph size={34} task={glyphTask(definition, problems)} />
      </motion.span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">
          <span>Telemetry · Task editor</span>
          <span aria-hidden className={`size-1.5 rounded-full ${saved ? "bg-ion" : "bg-halo"}`} />
          <span className="truncate normal-case tracking-normal">
            {saved ? definition.id : "unsaved"}
          </span>
        </div>
        <h1 className="m-0">
          <input
            value={definition.name}
            onChange={(e) => setDefinition({ ...definition, name: e.target.value })}
            aria-label="Task name"
            className="-ml-1.5 w-full max-w-[520px] rounded-sm border border-transparent bg-transparent px-1.5 font-display text-[20px] leading-tight text-starlight transition-colors hover:border-halo focus:border-pulsar focus:outline-none"
          />
        </h1>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {problems > 0 && (
          <Popover
            open={problemsOpen}
            onOpenChange={onProblemsOpen}
            label="Problems"
            width={380}
            trigger={
              <span className="flex items-center gap-1.5 text-status-error">
                <CircleAlert size={12} strokeWidth={1.75} />
                {problems} problem{problems === 1 ? "" : "s"}
              </span>
            }
          >
            <ProblemsList diagnostics={diagnostics} onJump={(d) => {
              onProblemsOpen(false);
              onJump(d);
            }} />
          </Popover>
        )}

        <StartMeter startLine={session.startLine} />

        <Popover
          open={detailsOpen}
          onOpenChange={onDetailsOpen}
          label="Details"
          width={360}
          trigger={
            <>
              <FolderTree size={12} strokeWidth={1.75} />
              <span className="max-w-[140px] truncate">{detailsSummary(definition)}</span>
            </>
          }
        >
          <TaskDetailsBody definition={definition} categories={categories} onChange={setDefinition} />
        </Popover>

        {session.checking && <span className="text-[10px] text-static/60">checking…</span>}

        {session.dirty && (
          <>
            {session.baseline && (
              <button
                type="button"
                onClick={session.revert}
                className="text-[11px] text-static transition-colors hover:text-starlight"
              >
                Revert
              </button>
            )}
            {/* The page's ONE primary control — matte Pulsar fill. Everything
                else on the header is quiet, which is what lets "there are
                unsaved edits" read at a glance. */}
            <button
              type="button"
              onClick={onSave}
              disabled={session.saving}
              className="rounded-sm bg-pulsar px-3 py-1 text-[11px] font-medium text-void transition-[filter] hover:brightness-108 disabled:opacity-50"
            >
              {session.saving ? "Saving…" : "Save"}
            </button>
          </>
        )}
      </div>

      {session.actionError && (
        <p className="w-full text-[11px] text-status-error">{session.actionError}</p>
      )}
    </header>
  );
}

/**
 * The `START` line's length against its cap.
 *
 * NOT DECORATION, AND NEVER HIDDEN. The cap is the one budget an operator can
 * exhaust without noticing: the firmware truncates an overlong line in silence
 * and runs on whichever values happened to fit. Each stage costs five tokens,
 * so the number is worth watching while the ramp grows (`TASKS.md#the-start-line`).
 */
export function StartMeter({ startLine }: { startLine: { length: number; max: number } | null }) {
  if (!startLine) return null;
  const used = startLine.length / startLine.max;
  const over = startLine.length - startLine.max;
  const tone = used > 0.9 ? "var(--color-status-error)" : "var(--color-pulsar)";
  return (
    <span
      title={`The START line is ${startLine.length} of ${startLine.max} bytes. Over the cap, the firmware truncates it without saying so.`}
      className="flex items-center gap-1.5 font-mono text-[10px] text-static/80"
    >
      <span className="tracking-[0.14em] text-static/60 uppercase">start</span>
      <span className="h-1 w-14 overflow-hidden rounded-full bg-halo/70">
        <motion.span
          className="block h-full rounded-full"
          initial={false}
          animate={{ width: `${Math.min(100, used * 100)}%`, backgroundColor: tone }}
        />
      </span>
      <span className="tabular-nums" style={over > 0 ? { color: "var(--color-status-error)" } : undefined}>
        {startLine.length}/{startLine.max}
      </span>
      {over > 0 && (
        <span style={{ color: "var(--color-status-error)" }}>
          over by {over} — the firmware truncates in silence
        </span>
      )}
    </span>
  );
}

const HOME_TITLE: Record<ProblemHome["kind"], string> = {
  row: "Trial types",
  generation: "Trial generation",
  holds: "Holds & shaping",
  task: "Task",
};

function ProblemsList({
  diagnostics,
  onJump,
}: {
  diagnostics: TaskDiagnostic[];
  onJump: (diagnostic: TaskDiagnostic) => void;
}) {
  const groups = new Map<ProblemHome["kind"], TaskDiagnostic[]>();
  for (const d of diagnostics) {
    const kind = homeOf(d).kind;
    groups.set(kind, [...(groups.get(kind) ?? []), d]);
  }
  return (
    <div className="scrollbar-slim flex max-h-[60vh] flex-col gap-3 overflow-y-auto">
      <p className="text-[11px] leading-relaxed text-static">
        A task saves and flashes with problems outstanding — read these first, because most of
        them run and record the wrong thing rather than fail.
      </p>
      {[...groups].map(([kind, list]) => (
        <section key={kind} className="flex flex-col gap-1">
          <h3 className="font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">
            {HOME_TITLE[kind]}
          </h3>
          {list.map((d, i) => {
            const home = homeOf(d);
            return (
              <button
                key={i}
                type="button"
                onClick={() => onJump(d)}
                className="flex items-start gap-1.5 rounded-sm px-1.5 py-1 text-left text-[11px] leading-snug text-starlight/90 transition-colors hover:bg-halo/40"
              >
                <TriangleAlert size={11} strokeWidth={1.75} className="mt-0.5 shrink-0 text-status-error" />
                <span>
                  <span className="font-mono text-[10px] text-status-error">{d.code}</span>
                  {home.kind === "row" && (
                    <span className="font-mono text-[10px] text-static"> · row {home.row + 1}</span>
                  )}{" "}
                  {d.message}
                </span>
              </button>
            );
          })}
        </section>
      ))}
    </div>
  );
}

/** What the task glyph draws, from the definition on screen. */
function glyphTask(definition: TaskDefinition, problems: number) {
  return {
    id: definition.id,
    trials: definition.trials.length,
    stages: definition.stages.length,
    selectionMode: definition.selectionMode,
    problems,
  };
}
