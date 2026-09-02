import { motion } from "framer-motion";
import { Trash2, TriangleAlert } from "lucide-react";

import { colorForIndex } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import type { TaskEntry } from "@/lib/taskdef/types";

import { TaskGlyph } from "./TaskGlyph";

/**
 * One saved task profile, as a card.
 *
 * It replaced a row in a text list. The difference the card buys is that a task
 * has a SHAPE — how many conditions, whether it eases in, how the next trial is
 * drawn — and none of that was visible without opening it. The glyph states all
 * three (`TaskGlyph`) and the strip and fact line spell them out underneath,
 * because a mark is scannable and a sentence is checkable and the shelf wants
 * both.
 *
 * **The HUD tile idiom, not the cohort card's.** An icon-headed frosted tile
 * with a hairline between its header and its body is what every other landing
 * on this app is built from (`SummaryCard`, `HudTile`, `EntranceTile`), and
 * a task card is one more of them: the glyph sits where the icon would.
 *
 * **Colour is the condition strip.** Each square is one condition in the series
 * slot it wears everywhere — its glyph node, its trial-table badge, its
 * state-machine tick, its Analytics curve — so a card and the editor it opens
 * agree about which colour "condition 3" is before either is read. Status
 * colour is state only: Ion for a task with nothing wrong, the error tone for a
 * count of problems, nothing else.
 *
 * `editedAt` finally appears here. `tasks.list` has always carried it and
 * nothing had ever drawn it, which on a rig where three people edit the same
 * library is the one fact that says whose version this is.
 *
 * DELETE LIVES ON THE CARD, not in the editor. It used to be a trash icon in
 * the editor header, reachable only from inside the thing being deleted and
 * only while it had no unsaved edits. Deleting is a library gesture; the
 * confirm is the caller's, because it names the task.
 */
export function TaskCard({
  task,
  onOpen,
  onDelete,
}: {
  task: TaskEntry;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const ready = task.problems === 0;
  return (
    <motion.div
      whileHover={{ y: -3, scale: 1.015 }}
      whileTap={{ scale: 0.995 }}
      transition={springSnappy}
      // `group` for the trash's reveal; `relative` for its corner. The card
      // itself is the button — a nested <button> is invalid HTML and the trash
      // would be unreachable by keyboard inside one.
      className="group relative"
    >
      <button
        type="button"
        onClick={onOpen}
        className="hud flex w-full flex-col overflow-hidden rounded-md text-left transition-colors hover:border-static/40"
      >
        {/* Header: the glyph where a tile's icon goes, the name, the folder. */}
        <span className="flex items-center gap-3 px-3.5 pb-2.5 pt-3">
          <motion.span layoutId={`task-glyph-${task.id}`} className="flex shrink-0">
            <TaskGlyph task={task} size={44} />
          </motion.span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-display text-[13px] font-medium text-starlight">
              {task.name}
            </span>
            <span className="mt-0.5 block truncate font-mono text-[9px] uppercase tracking-wide text-static/70">
              {task.category} · {task.selectionMode === "pool" ? "pool" : "anti-bias"}
            </span>
          </span>
        </span>

        {/* The condition strip: one square per condition in its own colour. A
            task with no conditions yet shows the gap where they would go, so an
            unfinished task reads as unfinished rather than as a different kind
            of thing. */}
        <span className="flex items-center gap-1 px-3.5 pb-2.5" aria-hidden>
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

        {/* Body: the facts, then the state. */}
        <span className="flex w-full items-center gap-2 border-t border-halo px-3.5 py-2">
          {/* Two facts here; the selection mode rides the category line above,
              because three plus the status badge does not fit a grid cell. */}
          <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-static">
            {task.trials} condition{task.trials === 1 ? "" : "s"} ·{" "}
            {task.stages === 1 ? "no ramp" : `${task.stages} stages`}
          </span>
          {ready ? (
            <span
              className="flex shrink-0 items-center gap-1 font-mono text-[10px]"
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
              className="flex shrink-0 items-center gap-0.5 font-mono text-[10px] text-status-error"
            >
              <TriangleAlert size={10} strokeWidth={1.75} />
              {task.problems}
            </span>
          )}
        </span>
        <span className="block w-full truncate px-3.5 pb-2.5 font-mono text-[10px] text-static/60">
          {editedLabel(task.editedAt)}
        </span>
      </button>

      {/* Revealed on hover, and on keyboard focus — `opacity-0` alone would
          make it focusable but invisible, which is worse than absent. */}
      <button
        type="button"
        onClick={onDelete}
        title={`Delete ${task.name}`}
        aria-label={`Delete ${task.name}`}
        className="absolute right-2 top-2 rounded-sm p-1 text-static opacity-0 transition-opacity hover:text-status-error focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Trash2 size={13} strokeWidth={1.75} />
      </button>
    </motion.div>
  );
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
