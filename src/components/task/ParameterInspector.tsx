import { RotateCcw } from "lucide-react";
import { useMemo } from "react";

import { ConfigFields } from "@/components/sessions/ConfigFields";
import {
  groupsOfTab,
  nodesGovernedByTab,
  orderGroups,
  tabOf,
  type TaskGraphModel,
} from "@/lib/tasks/topology";
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
 * `exclude` drops groups another surface already owns. The task editor passes
 * the ramp groups, because `StageRamp` edits those four holds as a table and a
 * ramp is only legible as a sequence of rows — showing them here as well would
 * be TWO SURFACES FOR ONE FIELD, which is the thing that eventually disagrees.
 * An excluded group keeps its Pulsar dot logic out of the pills but is still
 * counted as diverging, so nothing about it goes quiet.
 *
 * The pills are the same set the machine's chips name, and the two select the
 * same state: clicking a chip, clicking a node, or clicking a pill all land
 * here. A pill lights (border, like a tile did) while a hovered state is
 * governed by its group, carries a Pulsar dot while any of its values diverge
 * from the sketch's own, and hovering it lights the machine — the tiles'
 * hover contract, moved onto smaller furniture.
 *
 * A PILL IS A TAB, NOT A GROUP (`topology.tabOf`). Correction trials and reward
 * volumes are session settings that were each carrying a pill of their own, so
 * the rail folds them under Session and `ConfigFields` renders them as
 * sub-sections there. The fold is the rail's alone: `group` is inside
 * `profile_hash`, so it cannot be the thing that moves. Everything the pill
 * computes — the dot, the lit border, the governed states, the reset count —
 * therefore reduces its groups through `tabOf` first.
 */
export function ParameterInspector({
  profile,
  model,
  config,
  baseline,
  selected,
  exclude,
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
  /** Groups another editor owns. Absent means show everything. */
  exclude?: (group: string) => boolean;
  onSelect: (group: string) => void;
  onChange: (next: Record<string, unknown>) => void;
  onHoverGroup: (group: string | null) => void;
  /** Groups the hovered *state* is tuned by — the machine→rail half of the link. */
  litGroups: Set<string>;
}) {
  /** Groups this profile declares that some pill is allowed to show. `exclude`
   *  tests the RAW group (`isRampGroup`), because that is what it names. */
  const declared = useMemo(() => {
    const out = new Set<string>();
    for (const field of profile?.config ?? []) {
      if (field.group && !exclude?.(field.group)) out.add(field.group);
    }
    return out;
  }, [profile, exclude]);

  const tabs = useMemo(
    () => orderGroups(new Set([...declared].map(tabOf))),
    [declared],
  );

  if (!profile || tabs.length === 0) return null;

  const tab = selected !== null && tabs.includes(selected) ? selected : tabs[0]!;
  const members = groupsOfTab(tab, declared);
  const fields = profile.config.filter((f) => f.group && tabOf(f.group) === tab);
  const changed = fields.filter(
    (f) =>
      f.metadataKey in config && !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
  );
  const states = nodesGovernedByTab(model, tab).map((n) => n.label);

  /** Which tabs carry values this rig changed — the pill dots. */
  const diverging = new Set(
    profile.config
      .filter(
        (f) =>
          f.group &&
          f.metadataKey in config &&
          !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
      )
      .map((f) => tabOf(f.group as string)),
  );

  return (
    <div className="hud flex min-h-0 flex-col rounded-md">
      <div className="flex flex-wrap gap-1 border-b border-halo p-2.5">
        {tabs.map((name) => {
          const active = name === tab;
          // `litGroups` is a hovered NODE's `governedBy` — raw groups. A folded
          // pill has to light for any of the groups it swallowed.
          const lit = [...litGroups].some((g) => tabOf(g) === name);
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
            <div className="truncate text-[12px] font-medium text-starlight">{tab}</div>
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
          only={members}
          quiet
        />
      </div>
    </div>
  );
}
