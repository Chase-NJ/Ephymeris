import { ChevronRight } from "lucide-react";
import { Fragment, useMemo } from "react";

import { fillFor } from "./TaskGraph";
import type { TaskGraphModel, TaskNode } from "@/lib/tasks/topology";

/**
 * The trial flow as a strip — what the Trial flow card becomes once the operator
 * has scrolled down into the parameter tiles.
 *
 * The tile↔graph link is the point of the Task page: hovering a group lights the
 * states its numbers govern. A ~500px diagram at the top of a page of tiles
 * breaks exactly that, because by the time you reach the tile you care about,
 * the thing it lights is off-screen. So the card stays pinned and trades its
 * diagram for this: every node, still in trial order, still lit by the same
 * `highlighted` set, in a strip short enough to leave the tiles usable.
 *
 * Grouped by column, not laid out as one line, so the trial's real shape
 * survives the compression: a column is a moment in the trial, and a stack
 * inside one is the branches available at that moment (the two odor conditions,
 * an outcome fan, an abort hanging below its state). Same nodes, same colours as
 * `TaskGraph` — `fillFor` is imported rather than reimplemented.
 */
export function TaskRail({
  model,
  highlighted,
  onNodeClick,
}: {
  model: TaskGraphModel;
  /** Node ids to light — the parameter tile the operator is hovering. */
  highlighted?: ReadonlySet<string>;
  onNodeClick?: (node: TaskNode) => void;
}) {
  /** Nodes bucketed by column, in trial order, each bucket top-to-bottom. */
  const columns = useMemo(() => {
    const byColumn = new Map<number, TaskNode[]>();
    for (const node of model.nodes) {
      const bucket = byColumn.get(node.column);
      if (bucket) bucket.push(node);
      else byColumn.set(node.column, [node]);
    }
    return [...byColumn.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([column, nodes]) => ({ column, nodes: [...nodes].sort((a, b) => a.row - b.row) }));
  }, [model]);

  if (!model.usable) return null;

  const someoneLit = (highlighted?.size ?? 0) > 0;

  return (
    <div className="flex flex-wrap items-start gap-x-1.5 gap-y-2">
      {columns.map((column, index) => (
        <Fragment key={column.column}>
          {index > 0 && (
            <ChevronRight
              size={11}
              strokeWidth={1.75}
              className="mt-[3px] shrink-0 text-static/35"
              aria-hidden
            />
          )}
          <div className="flex flex-col gap-0.5">
            {column.nodes.map((node) => {
              const lit = !someoneLit || highlighted!.has(node.id);
              return (
                <button
                  key={node.id}
                  type="button"
                  onClick={onNodeClick ? () => onNodeClick(node) : undefined}
                  title={node.detail ? `${node.label}\n${node.detail}` : node.label}
                  className="flex items-center gap-1.5 text-left transition-opacity"
                  style={{ opacity: lit ? 1 : 0.32 }}
                >
                  <span
                    className="size-[5px] shrink-0 rounded-full"
                    style={{ backgroundColor: fillFor(node) }}
                  />
                  <span
                    className="text-[10px] whitespace-nowrap"
                    style={{
                      color: lit ? "var(--color-starlight)" : "var(--color-static)",
                    }}
                  >
                    {node.label}
                  </span>
                </button>
              );
            })}
          </div>
        </Fragment>
      ))}
    </div>
  );
}
