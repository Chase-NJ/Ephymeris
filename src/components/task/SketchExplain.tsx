import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { ConfigField, TaskProfile } from "@/lib/sessions/types";
import {
  nodesGovernedBy,
  nodesGovernedByTab,
  tabOf,
  type TaskGraphModel,
} from "@/lib/tasks/topology";

/**
 * What the parameter under the cursor actually means — the wizard's
 * `ExplainTile` motif (born in the removed spec editor), worn by the
 * sketch library.
 *
 * Same three rules as the original. IT FOLLOWS FOCUS, ONE DEFINITION AT A
 * TIME: a behaviour sketch declares forty-odd tunables, and forty inline
 * captions was the wall this page used to be — with the tile carrying the
 * prose, the form itself can go quiet (`ConfigFields`' `quiet` prop) and read
 * as a scannable column of values. IT ANSWERS AT EVERY ALTITUDE: at rest it
 * describes the selected sketch, a hovered *group* describes the moment of
 * the trial it governs, a hovered *field* gets the full treatment — help,
 * wire token, range, and whether this rig has moved it off the author's
 * value. THE PLUMBING IS ONE COMPONENT: `ConfigFields`' leaf reports through
 * a context whose default is a no-op, so the mapping step — which mounts the
 * same form with no provider — is untouched.
 *
 * A parallel context rather than a reuse of the spec editor's: `Explained`
 * there is shaped by overlay keys and spec paths, and generalising it would
 * couple the wizard's schema types to a page that reads `task.json` profiles.
 * The *motif* is shared; the payload is each surface's own.
 */

export interface SketchFocus {
  field: ConfigField;
  value: unknown;
}

const SketchExplainContext = createContext<{
  focus: SketchFocus | null;
  report: (next: SketchFocus | null) => void;
}>({ focus: null, report: () => {} });

export function SketchExplainProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<SketchFocus | null>(null);
  const value = useMemo(() => ({ focus, report: setFocus }), [focus]);
  return (
    <SketchExplainContext.Provider value={value}>
      {children}
    </SketchExplainContext.Provider>
  );
}

export function useSketchExplain() {
  return useContext(SketchExplainContext);
}

export function SketchExplainTile({
  profile,
  model,
  authored,
  hoverGroup,
  sketchName,
}: {
  profile: TaskProfile | null;
  model: TaskGraphModel;
  /** The sketch author's own defaults — what "this rig changed it" means. */
  authored: Record<string, unknown>;
  /** The parameter group under the pointer, when no single field is. */
  hoverGroup: string | null;
  sketchName: string;
}) {
  const { focus } = useSketchExplain();
  const entry =
    focus !== null
      ? explainField(focus, model, authored)
      : hoverGroup !== null && profile !== null
        ? explainGroup(hoverGroup, profile, model)
        : profile !== null
          ? explainSketch(profile, model, sketchName)
          : null;

  return (
    <aside className="hud rounded-md px-3 py-2.5">
      <div className="font-mono text-[10px] tracking-wider text-static uppercase">
        {focus !== null
          ? "This parameter"
          : hoverGroup !== null
            ? "This group"
            : "This sketch"}
      </div>

      {entry === null ? (
        <>
          <div className="mt-1.5 font-mono text-[11px] text-starlight">
            Nothing selected
          </div>
          <p className="mt-1 text-[10.5px] leading-relaxed text-static">
            Pick a sketch from the library. Its trial flow and this
            rig&rsquo;s parameters for it appear on the right, and hovering a
            parameter puts its meaning here.
          </p>
        </>
      ) : (
        <>
          <div className="mt-1.5 font-mono text-[11px] break-words text-starlight">
            {entry.title}
          </div>
          {entry.kicker && (
            <div className="mt-0.5 font-mono text-[9.5px] text-static/70">
              {entry.kicker}
            </div>
          )}
          {entry.body.map((line, i) => (
            <p key={i} className="mt-1.5 text-[10.5px] leading-relaxed text-static">
              {line}
            </p>
          ))}
        </>
      )}
    </aside>
  );
}

interface Entry {
  title: string;
  kicker: string | null;
  body: string[];
}

/**
 * One focused field, most specific first: the author's help, then the range
 * and default, then this rig's divergence — the one line only this page can
 * write, since it owns the middle layer of the merge (`tasks.md` §6.1).
 */
function explainField(
  focus: SketchFocus,
  model: TaskGraphModel,
  authored: Record<string, unknown>,
): Entry {
  const { field, value } = focus;
  const kicker = [
    field.wireKey ? `START ${field.wireKey}` : null,
    field.unit ? `in ${field.unit}` : null,
    field.type,
  ]
    .filter(Boolean)
    .join(" · ");

  const body: string[] = [];
  if (field.help) body.push(field.help);

  const range =
    field.min !== undefined && field.max !== undefined
      ? ` The form clamps to ${fmt(field.min)}–${fmt(field.max)}${field.unit ? ` ${field.unit}` : ""}.`
      : "";
  body.push(`The sketch's own value is ${fmt(field.default)}${field.unit ? ` ${field.unit}` : ""}.${range}`);

  const own = authored[field.metadataKey];
  if (!Object.is(value, own) && !(typeof value === "string" && value.trim() !== "")) {
    body.push(
      `This rig runs ${fmt(value)}${field.unit ? ` ${field.unit}` : ""} instead — saved here, still overridable per animal at mapping.`,
    );
  }

  const governed = nodesGovernedBy(model, field.group ?? null).map((n) => n.label);
  if (governed.length > 0) {
    // Capped: a broad group like "Holds & windows" touches a dozen states, and
    // a twelve-item list is a wall — the graph above is already lighting them.
    const shown = governed.slice(0, 4);
    const more = governed.length - shown.length;
    body.push(`Governs ${shown.join(" · ")}${more > 0 ? ` · +${more} more` : ""}.`);
  }

  return { title: field.label, kicker: kicker || null, body };
}

/** A hovered pill: which moment of the trial this TAB is.
 *
 *  A tab, not a group: the rail folds a few groups into one pill
 *  (`topology.tabOf`) and this is what the pill's hover reports. A field's own
 *  explanation above stays on the exact group, because a correction field does
 *  not govern the states `num_trials` does. */
function explainGroup(
  tab: string,
  profile: TaskProfile,
  model: TaskGraphModel,
): Entry {
  const group = tab;
  const fields = profile.config.filter((f) => f.group && tabOf(f.group) === tab);
  const governed = nodesGovernedByTab(model, tab).map((n) => n.label);
  const body: string[] = [];
  if (governed.length > 0) {
    const shown = governed.slice(0, 4);
    const more = governed.length - shown.length;
    body.push(
      `These ${fields.length} parameter${fields.length === 1 ? "" : "s"} govern ${shown.join(" · ")}${more > 0 ? ` · +${more} more` : ""} — lit on the flow above.`,
    );
  } else {
    body.push(
      `${fields.length} parameter${fields.length === 1 ? "" : "s"} with no single state to point at — session-wide settings.`,
    );
  }
  body.push("Hover a parameter and this becomes its definition.");
  return { title: group, kicker: `${fields.length} parameters`, body };
}

/** The resting subject: the selected sketch itself. */
function explainSketch(
  profile: TaskProfile,
  model: TaskGraphModel,
  sketchName: string,
): Entry {
  const body: string[] = [];
  if (model.usable) {
    body.push(
      `Declares ${profile.config.length} operator-tunable parameters and ${model.conditions.length} scored condition${model.conditions.length === 1 ? "" : "s"}. The trial flow is derived from its own strobe vocabulary — the branches drawn are the ones the firmware can report.`,
    );
  } else {
    body.push(
      profile.config.length > 0
        ? `Declares ${profile.config.length} parameters and no behavioural strobes — a utility sketch, driven from Debug Mode.`
        : "Declares no parameters — it runs a bare START.",
    );
  }
  body.push("Hover a parameter on the right and its meaning appears here.");
  return {
    title: profile.taskName ?? sketchName,
    kicker: profile.kind ?? null,
    body,
  };
}

function fmt(value: unknown): string {
  if (typeof value === "boolean") return value ? "on" : "off";
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}
