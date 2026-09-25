import { motion } from "framer-motion";
import { Copy, Trash2, TriangleAlert } from "lucide-react";

import { colorForIndex } from "@/lib/analytics/view";
import type { TaskEntry } from "@/lib/taskdef/types";

import { TaskGlyph } from "./TaskGlyph";

/**
 * One saved task profile, as a row in the Task landing's list.
 *
 * It was a card in a four-column grid, and before that a row in a text list.
 * The grid made a shelf of a dozen near-identical tasks hard to scan — the eye
 * zig-zags across cells, and the fact that separates two variants (a stage
 * count, a condition more) sits in a different place in each. A list lines the
 * facts up in columns, so the difference is where the eye already is. What the
 * card bought is kept: the glyph (`TaskGlyph`) still states a task's SHAPE — how
 * many conditions, whether it eases in, how the next trial is drawn — at a
 * glance, and its `layoutId` still flies into the editor it opens.
 *
 * **Colour is the condition strip.** Each square is one condition in the series
 * slot it wears everywhere — its glyph node, its trial-table badge, its
 * state-machine tick, its Analytics curve. Status colour is state only: Ion for
 * a task with nothing wrong, the error tone for a count of problems.
 *
 * DUPLICATE AND DELETE LIVE ON THE ROW, revealed on hover or keyboard focus.
 * Both are library gestures rather than edits: Duplicate opens an unsaved copy
 * in the editor, and the delete confirm is the caller's, because it names the
 * task. The row itself is not a `<button>` wrapping them — nested buttons are
 * invalid HTML and the actions would be unreachable by keyboard.
 */
export function TaskRow({
  task,
  onOpen,
  onDuplicate,
  onDelete,
}: {
  task: TaskEntry;
  onOpen: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const ready = task.problems === 0;
  return (
    <div className="group relative flex items-center transition-colors hover:bg-nebula/60">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-4 py-2.5 pl-4 pr-2 text-left"
      >
        <motion.span layoutId={`task-glyph-${task.id}`} className="flex shrink-0">
          <TaskGlyph task={task} size={32} />
        </motion.span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-starlight">
            {task.name}
          </span>
          <span className="mt-0.5 block truncate font-mono text-[9px] uppercase tracking-wide text-static/70">
            {task.category} · {modeLabel(task.selectionMode)}
          </span>
        </span>

        {/* The condition strip: one square per condition in its own colour. A
            task with no conditions yet shows the gap where they would go. */}
        <span className="hidden w-24 shrink-0 items-center gap-0.5 md:flex" aria-hidden>
          {task.trials === 0 ? (
            <span className="h-1.5 w-full rounded-sm border border-dashed border-halo" />
          ) : (
            Array.from({ length: Math.min(task.trials, 8) }, (_, i) => (
              <span
                key={i}
                className="h-1.5 flex-1 rounded-sm"
                style={{ background: colorForIndex(i) }}
              />
            ))
          )}
        </span>

        <span className="w-36 shrink-0 truncate font-mono text-[10px] text-static">
          {task.trials} condition{task.trials === 1 ? "" : "s"} ·{" "}
          {task.stages === 1 ? "no ramp" : `${task.stages} stages`}
        </span>

        <span className="w-14 shrink-0">
          {ready ? (
            <span
              className="flex items-center gap-1 font-mono text-[10px]"
              style={{ color: "var(--color-status-ok)" }}
            >
              <span
                className="size-1.5 rounded-full"
                style={{ background: "var(--color-status-ok)" }}
              />
              ready
            </span>
          ) : (
            <span
              title={`${task.problems} problem${task.problems === 1 ? "" : "s"} — it will still flash, but check it first`}
              className="flex items-center gap-0.5 font-mono text-[10px] text-status-error"
            >
              <TriangleAlert size={10} strokeWidth={1.75} />
              {task.problems}
            </span>
          )}
        </span>

        <span className="hidden w-28 shrink-0 truncate font-mono text-[10px] text-static/60 lg:block">
          {editedLabel(task.editedAt)}
        </span>
      </button>

      {/* Revealed on hover, and on keyboard focus — `opacity-0` alone would
          make them focusable but invisible, which is worse than absent. */}
      <span className="flex shrink-0 items-center gap-0.5 pr-3">
        <button
          type="button"
          onClick={onDuplicate}
          title={`Start a new task from ${task.name}`}
          aria-label={`Duplicate ${task.name}`}
          className="rounded-sm p-1.5 text-static opacity-0 transition-opacity hover:text-starlight focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Copy size={13} strokeWidth={1.75} />
        </button>
        <button
          type="button"
          onClick={onDelete}
          title={`Delete ${task.name}`}
          aria-label={`Delete ${task.name}`}
          className="rounded-sm p-1.5 text-static opacity-0 transition-opacity hover:text-status-error focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Trash2 size={13} strokeWidth={1.75} />
        </button>
      </span>
    </div>
  );
}

function modeLabel(mode: TaskEntry["selectionMode"]): string {
  return mode === "pool" ? "pool" : mode === "weighted" ? "weighted" : "anti-bias";
}

/**
 * "edited 3d ago", or the date once that stops being useful.
 *
 * Relative only inside a week: past that "edited 43d ago" is arithmetic the
 * reader has to do, and the date is the thing they were going to work out
 * anyway.
 */
function editedLabel(editedAt: string | null): string {
  if (!editedAt) return "never saved";
  const then = Date.parse(editedAt);
  if (Number.isNaN(then)) return "";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "edited today";
  if (days === 1) return "edited yesterday";
  if (days < 7) return `edited ${days}d ago`;
  return `edited ${editedAt.slice(0, 10)}`;
}
