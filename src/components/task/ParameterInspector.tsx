import { RotateCcw } from "lucide-react";
import { useMemo } from "react";

import { ConfigFields } from "@/components/sessions/ConfigFields";
import { nodesGovernedBy, orderGroups, type TaskGraphModel } from "@/lib/tasks/topology";
import type { TaskProfile } from "@/lib/sessions/types";

/**
 * The parameter rail — every group reachable, one group in view.
 *
 * This replaced `ParameterTiles`, which laid all thirteen groups out as a long
 * two-column scroll. The rail holds the whole set as **pills** and shows the
 * selected group's fields beneath them, so configuring any parameter is a
 * selection, never a scroll — the machine stays on screen the whole time,
 * which is the point: the highlight link is worthless when one end of it is
 * below the fold.
 *
 * The pills are the same set the machine's chips name, and the two select the
 * same state: clicking a chip, clicking a node, or clicking a pill all land
 * here. A pill lights (border, like a tile did) while a hovered state is
 * governed by its group, carries a Pulsar dot while any of its values diverge
 * from the sketch's own, and hovering it lights the machine — the tiles'
 * hover contract, moved onto smaller furniture.
 */
export function ParameterInspector({
  profile,
  model,
  config,
  baseline,
  selected,
  onSelect,
  onChange,
  onHoverGroup,
  litGroups,
}: {
  profile: TaskProfile | null;
  model: TaskGraphModel;
  config: Record<string, unknown>;
  /** The profile's own defaults — what "changed" and "reset" are measured against. */
  baseline: Record<string, unknown>;
  selected: string | null;
  onSelect: (group: string) => void;
  onChange: (next: Record<string, unknown>) => void;
  onHoverGroup: (group: string | null) => void;
  /** Groups the hovered *state* is tuned by — the machine→rail half of the link. */
  litGroups: Set<string>;
}) {
  const groups = useMemo(() => {
    const declared = new Set<string>();
    for (const field of profile?.config ?? []) {
      if (field.group) declared.add(field.group);
    }
    return orderGroups(declared);
  }, [profile]);

  if (!profile || groups.length === 0) return null;

  const group = selected !== null && groups.includes(selected) ? selected : groups[0]!;
  const fields = profile.config.filter((f) => f.group === group);
  const changed = fields.filter(
    (f) =>
      f.metadataKey in config && !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
  );
  const states = nodesGovernedBy(model, group).map((n) => n.label);

  /** Which groups carry values this rig changed — the pill dots. */
  const diverging = new Set(
    profile.config
      .filter(
        (f) =>
          f.group &&
          f.metadataKey in config &&
          !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
      )
      .map((f) => f.group as string),
  );

  return (
    <div className="hud flex min-h-0 flex-col rounded-md">
      <div className="flex flex-wrap gap-1 border-b border-halo p-2.5">
        {groups.map((name) => {
          const active = name === group;
          const lit = litGroups.has(name);
          return (
            <button
              key={name}
              type="button"
              onClick={() => onSelect(name)}
              onPointerEnter={() => onHoverGroup(name)}
              onPointerLeave={() => onHoverGroup(null)}
              onFocusCapture={() => onHoverGroup(name)}
              className={`flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors ${
                active
                  ? "border-transparent bg-pulsar/18 text-starlight"
                  : lit
                    ? "border-pulsar text-starlight"
                    : "border-transparent text-static hover:text-starlight"
              }`}
            >
              {name}
              {diverging.has(name) && (
                <span
                  aria-hidden
                  title="This rig changed values here"
                  className="size-1 rounded-full bg-pulsar"
                />
              )}
            </button>
          );
        })}
      </div>

      {/* The selected group. The rail's own column scrolls as a last resort on
          a short window; a single group almost always fits outright. */}
      <div className="scrollbar-none min-h-0 overflow-y-auto p-3.5">
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
          quiet
        />
      </div>
    </div>
  );
}
