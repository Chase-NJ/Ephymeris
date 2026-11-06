import { Check, Plus, RotateCcw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { TextInput } from "@/components/common/controls";
import { ConfigFields } from "@/components/sessions/ConfigFields";
import {
  expose,
  exposedFields,
  exposedGroups,
  hideAndReset,
  pickerGroups,
  showValue,
} from "@/lib/taskdef/exposure";
import { inactiveNote } from "@/lib/taskdef/selection";
import type { SelectionMode, StageRow, TaskDiagnostic } from "@/lib/taskdef/types";
import { HOLDS_TAB, nodesGovernedByTab, tabOf } from "@/lib/tasks/topology";
import type { TaskProfile } from "@/lib/ws/protocol";

import { Panel } from "./Panel";
import { Popover } from "./Popover";
import { StageList } from "./StageList";

/**
 * The task's parameters (`TASKS.md#parameters`): the ones this task exposes,
 * as plain fields grouped the way the profile groups them, and the ramp.
 *
 * EVERYTHING STARTS HIDDEN. A new task's forty-odd parameters are all at
 * their defaults and none is on screen; the operator adds the ones they mean
 * to tune through the **Add parameter** picker, which lists every parameter by
 * group with its current value and its default, searchable. Only the exposed
 * ones are drawn here and offered in the Start dialog, and the list is saved
 * with the task (`definition.exposed`). A hidden parameter still rides the
 * `SET` lines at its default: exposure is presentation, never the wire.
 *
 * A field is a numeric input with its unit, a toggle, or a select, with the
 * profile's `min`/`max` enforced on the input (`FieldRow`). Reset-and-hide is
 * one click in the picker; a reset that keeps the field is the group header's.
 *
 * The ramp (`StageList`) is always here: it is the definition's own, with its
 * rows and not a parameter list, and a one-row ramp is a task that does not ramp.
 */
export function ParameterPanel({
  profile,
  model,
  config,
  baseline,
  exposed,
  mode,
  stages,
  diagnostics,
  litGroups,
  focusGroup,
  onFocusGroupConsumed,
  onParams,
  onExposed,
  onStages,
  onHoverGroup,
}: {
  profile: TaskProfile | null;
  model: Parameters<typeof nodesGovernedByTab>[0];
  config: Record<string, unknown>;
  baseline: Record<string, unknown>;
  exposed: readonly string[];
  mode: SelectionMode;
  stages: StageRow[];
  diagnostics: TaskDiagnostic[];
  /** Raw groups governing the state under the pointer — they light headers. */
  litGroups: ReadonlySet<string>;
  /** A group to open the picker on (a machine chip was clicked); consumed once. */
  focusGroup: string | null;
  onFocusGroupConsumed: () => void;
  onParams: (next: Record<string, unknown>) => void;
  onExposed: (next: string[]) => void;
  onStages: (next: StageRow[]) => void;
  onHoverGroup: (group: string | null) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");

  // A chip click opens the picker on that group's rows.
  useEffect(() => {
    if (!focusGroup) return;
    setQuery(focusGroup === HOLDS_TAB ? "" : focusGroup);
    setPickerOpen(true);
    onFocusGroupConsumed();
  }, [focusGroup, onFocusGroupConsumed]);

  const shown = useMemo(() => exposedFields(profile, exposed), [profile, exposed]);
  const groups = useMemo(() => exposedGroups(profile, exposed), [profile, exposed]);
  const exposable = (profile?.config ?? []).length;
  const hidden = Math.max(0, pickerGroups(profile, [], {}, {}).reduce((n, g) => n + g.entries.length, 0) - shown.length);
  const shownKeys = useMemo(() => new Set(shown.map((f) => f.metadataKey)), [shown]);

  const picker = useMemo(
    () => pickerGroups(profile, exposed, config, baseline, query),
    [profile, exposed, config, baseline, query],
  );

  const statesOf = (group: string) => nodesGovernedByTab(model, tabOf(group)).map((n) => n.label);

  return (
    <Panel
      id="params"
      name="Parameters"
      note={
        exposable === 0
          ? "none declared yet"
          : shown.length === 0
            ? `all ${hidden} at their defaults`
            : `${shown.length} shown · ${hidden} at their defaults`
      }
      right={
        <Popover
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          label="Add parameter"
          width={380}
          trigger={
            <>
              <Plus size={11} strokeWidth={2} />
              Add parameter
            </>
          }
        >
          <div className="flex flex-col gap-2">
            <div className="relative">
              <Search size={12} strokeWidth={1.75} className="pointer-events-none absolute top-2 left-2 text-static" />
              <TextInput
                label="Search parameters"
                value={query}
                onChange={setQuery}
                placeholder="search by name, group or unit"
                autoFocus
                className="w-full pl-7"
              />
            </div>
            <div className="scrollbar-slim -mr-2 flex max-h-[min(50vh,420px)] flex-col gap-3 overflow-y-auto pr-2">
              {picker.length === 0 && (
                <p className="py-3 text-center text-[11px] text-static">
                  {exposable === 0 ? "The profile declares no parameters yet." : "Nothing matches."}
                </p>
              )}
              {picker.map(({ group, entries }) => (
                <section key={group || "__ungrouped"} className="flex flex-col gap-0.5">
                  {group && (
                    <div className="border-b border-halo pb-0.5 font-mono text-[9.5px] tracking-[0.16em] text-static uppercase">
                      {group}
                    </div>
                  )}
                  {entries.map((entry) => {
                    const key = entry.field.metadataKey;
                    return (
                      <div
                        key={key}
                        className={`flex items-center gap-2 rounded-sm px-1.5 py-1 text-[11px] ${
                          entry.exposed ? "bg-pulsar/10" : "hover:bg-nebula/60"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => {
                            if (!entry.exposed) onExposed(expose(profile, exposed, key));
                          }}
                          title={entry.field.help ?? entry.field.label}
                          className="flex min-w-0 flex-1 items-center gap-2 text-left"
                        >
                          <span
                            className={`flex size-3.5 shrink-0 items-center justify-center rounded-[2px] border ${
                              entry.exposed ? "border-pulsar bg-pulsar text-void" : "border-static/60"
                            }`}
                            aria-hidden
                          >
                            {entry.exposed && <Check size={9} strokeWidth={3} />}
                          </span>
                          <span className={`truncate ${entry.exposed ? "text-starlight" : "text-static"}`}>
                            {entry.field.label}
                          </span>
                        </button>
                        <span
                          className={`shrink-0 font-mono text-[10px] ${entry.pinned ? "text-pulsar" : "text-static/70"}`}
                          title={entry.pinned ? `pinned; default ${showValue(entry.field, entry.defaultValue)}` : "at its default"}
                        >
                          {showValue(entry.field, entry.value)}
                          {entry.pinned && (
                            <span className="ml-1 text-static/60">· default {showValue(entry.field, entry.defaultValue)}</span>
                          )}
                        </span>
                        {entry.exposed && (
                          <button
                            type="button"
                            title="Return to its default and hide it"
                            aria-label={`Reset ${entry.field.label} and hide it`}
                            onClick={() => {
                              const out = hideAndReset(exposed, config, key);
                              onParams(out.config);
                              onExposed(out.exposed);
                            }}
                            className="shrink-0 text-static transition-colors hover:text-starlight"
                          >
                            <RotateCcw size={11} strokeWidth={1.75} />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </section>
              ))}
            </div>
            <p className="text-[10px] leading-relaxed text-static/70">
              A hidden parameter keeps its default and is still sent to the board. Exposed ones appear
              here and in the Start dialog.
            </p>
          </div>
        </Popover>
      }
      className="flex-1"
      bodyClassName="gap-2"
    >
      <div
        id="parameter-fields"
        className="scrollbar-slim relative -mr-2 flex min-h-0 flex-1 flex-col gap-3 overflow-x-hidden overflow-y-auto pr-2"
      >
        {shown.length === 0 ? (
          <p className="py-2 text-[11.5px] leading-relaxed text-static">
            Every parameter is at its default and out of sight. Add the ones this task tunes;
            only those are shown here and offered when a session starts.
          </p>
        ) : (
          groups.map((group) => {
            const lit = [...litGroups].some((g) => g === group);
            const states = statesOf(group);
            return (
              <section
                key={group || "__ungrouped"}
                onPointerEnter={() => onHoverGroup(tabOf(group))}
                onPointerLeave={() => onHoverGroup(null)}
                className="flex flex-col gap-1.5"
              >
                <header className={`flex items-baseline gap-2 border-b pb-1 ${lit ? "border-pulsar/70" : "border-halo/60"}`}>
                  <span className={`font-mono text-[10px] tracking-[0.16em] uppercase ${lit ? "text-pulsar" : "text-starlight"}`}>
                    {group || "Parameters"}
                  </span>
                  {states.length > 0 && (
                    <span className="min-w-0 truncate font-mono text-[9.5px] text-static/70" title={states.join(" · ")}>
                      tunes {states.join(" · ")}
                    </span>
                  )}
                </header>
                <ConfigFields
                  profile={profile}
                  config={config}
                  baseline={baseline}
                  onChange={onParams}
                  only={group}
                  quiet
                  fieldFilter={(f) => shownKeys.has(f.metadataKey)}
                  inactive={(f) => inactiveNote(mode, f)}
                  // Exposed is exposed: nothing folds behind a disclosure here.
                  isAdvanced={() => false}
                />
              </section>
            );
          })
        )}

        <section className="flex flex-col gap-1.5">
          <header
            className={`flex items-baseline gap-2 border-b pb-1 ${
              diagnostics.some((d) => d.location.startsWith("stages")) ? "border-status-error/70" : "border-halo/60"
            }`}
          >
            <span className="font-mono text-[10px] tracking-[0.16em] text-starlight uppercase">{HOLDS_TAB}</span>
            <span className="font-mono text-[9.5px] text-static/70">the ramp, one row per stage</span>
          </header>
          <StageList stages={stages} diagnostics={diagnostics} onChange={onStages} />
        </section>
      </div>
    </Panel>
  );
}
