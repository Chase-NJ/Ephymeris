import { motion } from "framer-motion";
import { RotateCcw } from "lucide-react";
import { useMemo } from "react";

import { ConfigFields } from "@/components/sessions/ConfigFields";
import { springPanel } from "@/lib/motion";
import { nodesGovernedBy, orderGroups, type TaskGraphModel } from "@/lib/tasks/topology";
import type { TaskProfile } from "@/lib/sessions/types";

/**
 * A sketch's parameters, one tile per declared group (`tasks.md` §6.1).
 *
 * Tiles are ordered the way the parameters take effect during a trial — session
 * setup, then the pool, then timing, then the ramp, then the policies that only
 * matter once an animal is answering — rather than by authored order. That is
 * what makes them build on each other: reading down the column is reading
 * through a trial, and it puts each number next to the moment it governs.
 * `orderGroups` owns the sequence, beside the node table it has to agree with.
 *
 * Hovering a tile lights the states its parameters govern on the graph above.
 * The highlight is plain React state lifted to the route rather than the
 * subscription store Analytics uses — that store exists to keep a hover from
 * re-rendering every animal row across several panels, and this is one page
 * lighting three nodes out of fifteen.
 */
export function ParameterTiles({
  profile,
  model,
  config,
  baseline,
  onChange,
  onHoverGroup,
  registerTile,
  quiet = false,
}: {
  profile: TaskProfile | null;
  model: TaskGraphModel;
  config: Record<string, unknown>;
  /** The profile's own defaults — what "changed" and "reset" are measured against. */
  baseline: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  onHoverGroup: (group: string | null) => void;
  /** Lets the route scroll a tile into view when its node is clicked. */
  registerTile: (group: string, el: HTMLElement | null) => void;
  /** Forwarded to `ConfigFields` — the explain tile carries the prose. */
  quiet?: boolean;
}) {
  const groups = useMemo(() => {
    const declared = new Set<string>();
    for (const field of profile?.config ?? []) {
      if (field.group) declared.add(field.group);
    }
    return orderGroups(declared);
  }, [profile]);

  if (!profile || groups.length === 0) return null;

  /** Which states this group's parameters govern — the tile's own subtitle. */
  const statesFor = (group: string) => nodesGovernedBy(model, group).map((n) => n.label);

  return (
    // Two columns at most: the library/explain column owns ~240px of the
    // page, and three-across made every row a crush of truncated labels.
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {groups.map((group, index) => {
        const fields = profile.config.filter((f) => f.group === group);
        const changed = fields.filter(
          (f) =>
            f.metadataKey in config &&
            !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
        );
        const states = statesFor(group);

        return (
          <motion.section
            key={group}
            ref={(el) => registerTile(group, el)}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...springPanel, delay: index * 0.04 }}
            onPointerEnter={() => onHoverGroup(group)}
            onPointerLeave={() => onHoverGroup(null)}
            onFocusCapture={() => onHoverGroup(group)}
            // scroll-mt clears the pinned trial-flow rail: a node click scrolls
            // its governing tile to the top edge, which without this lands
            // underneath the strip that sent you there.
            className="surface scroll-mt-[var(--task-rail-h)] rounded-md p-4 transition-colors hover:border-pulsar"
          >
            <header className="mb-2 flex items-baseline justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-[12px] font-medium text-starlight">{group}</div>
                {states.length > 0 && (
                  <div className="mt-0.5 truncate font-mono text-[10px] text-static/70">
                    {states.join(" · ")}
                  </div>
                )}
              </div>
              {changed.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    const next = { ...config };
                    for (const f of changed) next[f.metadataKey] = baseline[f.metadataKey];
                    onChange(next);
                  }}
                  className="flex shrink-0 items-center gap-1 text-[10px] text-static transition-colors hover:text-starlight"
                >
                  <RotateCcw size={10} strokeWidth={1.75} />
                  Reset {changed.length}
                </button>
              )}
            </header>
            <ConfigFields
              profile={profile}
              config={config}
              baseline={baseline}
              onChange={onChange}
              only={group}
              quiet={quiet}
            />
          </motion.section>
        );
      })}
    </div>
  );
}
