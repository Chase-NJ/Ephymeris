import { Plus, TriangleAlert } from "lucide-react";
import { useMemo } from "react";

import type { TaskEntry, TaskPreset } from "@/lib/taskdef/types";

/**
 * This rig's task profiles, grouped by category — the Task tab's left column.
 *
 * It replaced `SketchLibrary`, which listed the bundled sketches. The
 * difference is what a row IS: a bundled sketch is a fact about the build and
 * the same on every machine, while a profile belongs to this rig and can be
 * edited, renamed and deleted. So the list carries a problem count and a
 * create affordance, which a read-only library had no use for.
 *
 * THE BUNDLED SKETCHES HAVE NOT GONE ANYWHERE — the simulator and the utility
 * sketch are still flashable from Debug Mode, and a saved profile joins them in
 * the same picker at session mapping. What is not here is a *viewer* for them:
 * a bundled behaviour sketch would have nothing to edit, and offering one that
 * silently discarded edits is worse than not offering it.
 */
export function TaskLibrary({
  tasks,
  presets,
  selected,
  onSelect,
  onCreate,
}: {
  tasks: TaskEntry[];
  presets: TaskPreset[];
  selected: string | null;
  onSelect: (taskId: string) => void;
  onCreate: (presetId: string) => void;
}) {
  const grouped = useMemo(() => {
    const out = new Map<string, TaskEntry[]>();
    for (const task of tasks) {
      const list = out.get(task.category) ?? [];
      list.push(task);
      out.set(task.category, list);
    }
    return [...out.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [tasks]);

  return (
    <div className="hud flex flex-col rounded-md">
      <div className="scrollbar-none max-h-[46vh] overflow-y-auto py-1">
        {tasks.length === 0 && (
          <p className="px-3.5 py-4 text-[11px] leading-relaxed text-static/70">
            No tasks on this rig yet. Start from one of the presets below — they
            are the tasks this lab was running before the firmware was unified,
            transcribed value for value.
          </p>
        )}

        {grouped.map(([category, entries]) => (
          <div key={category}>
            <div className="px-3.5 pb-1 pt-2 font-mono text-[10px] uppercase tracking-wide text-static/60">
              {category}
            </div>
            {entries.map((task) => {
              const active = task.id === selected;
              return (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelect(task.id)}
                  className={`flex w-full items-center gap-2 px-3.5 py-1.5 text-left text-[12px] transition-colors ${
                    active
                      ? "bg-pulsar/18 text-starlight"
                      : "text-static hover:text-starlight"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{task.name}</span>
                  {task.problems > 0 && (
                    <span
                      title={`${task.problems} problem${task.problems === 1 ? "" : "s"} — it will still flash, but check it first`}
                      className="flex shrink-0 items-center gap-0.5 font-mono text-[10px] text-status-error"
                    >
                      <TriangleAlert size={10} strokeWidth={1.75} />
                      {task.problems}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      <div className="border-t border-halo px-3.5 py-2.5">
        <div className="mb-1.5 flex items-center gap-1 text-[10px] uppercase tracking-wide text-static/60">
          <Plus size={10} strokeWidth={2} />
          New from a preset
        </div>
        <div className="flex flex-col gap-0.5">
          {presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => onCreate(preset.id)}
              title={preset.summary}
              className="rounded-md px-1.5 py-1 text-left text-[11px] text-static transition-colors hover:bg-nebula/40 hover:text-starlight"
            >
              {preset.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
