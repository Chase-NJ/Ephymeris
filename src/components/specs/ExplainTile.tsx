import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { BAND_LABELS } from "@/lib/specs/layout";
import { BAND_TITLES } from "@/lib/specs/selection";
import type {
  ChannelRegistry,
  OverlayField,
  SpecCapabilities,
  SpecDocument,
  SpecSchema,
  StrobeRegistry,
} from "@/lib/specs/types";

/**
 * What the thing under the cursor actually means.
 *
 * A spec's tunables are firmware fields with lab names — `t_pen_noengage`,
 * `WATER_UNPOKE_EARLY_L`, `arm_after_stage` — and every one of them already has
 * a sentence written about it SOMEWHERE: the presentation overlay for the
 * fields, the template's `timing_defaults`/`outcome_defaults` for the durations
 * and outcome classes, the channel registry for the channels, the strobe
 * vocabulary for the codes. None of that prose could reach the operator, so the
 * wizard labelled things and left them unexplained.
 *
 * IT FOLLOWS FOCUS, ONE DEFINITION AT A TIME. The alternative — a standing
 * glossary of every tunable on the page — was considered and is worse here: a
 * step can carry twenty rows, most of which the operator is not asking about,
 * and a column of twenty definitions is a wall nobody reads. At rest it names
 * the epoch instead, which is the question someone who has not focused anything
 * yet is actually asking.
 *
 * IT ADDS, IT DOES NOT REPLACE. `FieldRow`'s inline caption stays: it is what
 * makes a field legible without a pointer, and a tile that only speaks on hover
 * would make the form worse for keyboard use, not better.
 *
 * THE PLUMBING IS ONE COMPONENT. `SpecField` is the single dispatcher every
 * generated spec field goes through, so reporting from there covers the wizard,
 * the Designer's form and the Inspector at once — and the shared
 * `FieldRow`/`rows.tsx` components other screens depend on are untouched.
 */

export interface Explained {
  /** The overlay key — `timing[].ms`. */
  overlayKey: string;
  /** The concrete path — `timing[3].ms`. */
  path: string;
  meta: OverlayField;
  value: unknown;
}

const ExplainContext = createContext<{
  focus: Explained | null;
  report: (next: Explained | null) => void;
}>({ focus: null, report: () => {} });

export function ExplainProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<Explained | null>(null);
  const value = useMemo(() => ({ focus, report: setFocus }), [focus]);
  return <ExplainContext.Provider value={value}>{children}</ExplainContext.Provider>;
}

export function useExplain() {
  return useContext(ExplainContext);
}

export function ExplainTile({
  doc,
  caps,
  schema,
  band,
}: {
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  /** The epoch this step edits — the resting subject. */
  band: number | null;
}) {
  const { focus } = useExplain();
  const entry = focus === null ? null : explain(focus, doc, caps, schema);

  return (
    <aside className="hud rounded-md px-3 py-2.5 lg:sticky lg:top-4 lg:self-start">
      <div className="font-mono text-[10px] tracking-wider text-static uppercase">
        {entry === null ? (band === null ? "What this is" : "This epoch") : "What this is"}
      </div>

      {entry === null ? (
        <>
          <div className="mt-1.5 font-mono text-[11px] text-starlight">
            {band === null ? "Nothing focused" : (BAND_TITLES[band] ?? BAND_LABELS[band])}
          </div>
          <p className="mt-1 text-[10.5px] leading-relaxed text-static">
            {band === null
              ? "Focus a field and its meaning appears here."
              : (EPOCH_NOTE[band] ??
                "Focus a field on this step and its meaning appears here.")}
          </p>
          {band !== null && (
            <p className="mt-2 text-[10px] leading-relaxed text-static/70">
              Focus any field on this step and this becomes its definition.
            </p>
          )}
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
 * Resolve one focused field, most specific source first.
 *
 * The overlay describes the FIELD; the template, the registries and the
 * vocabulary describe the VALUE. Both are worth saying and they answer
 * different questions, so where both exist both are shown — "what is a delay"
 * followed by "and this one is `errorDelay`, which serves both wrong-port and
 * omission".
 */
function explain(
  focus: Explained,
  doc: SpecDocument,
  caps: SpecCapabilities | null,
  schema: SpecSchema,
): Entry {
  const { overlayKey, path, meta, value } = focus;
  const body: string[] = [];
  let title = meta.label;
  let kicker: string | null = meta.unit ? `in ${meta.unit}` : null;

  const group = schema.overlay.groups.find((g) => g.id === meta.group);
  if (meta.help) body.push(meta.help);

  // A duration: name the id and hand over the template's own provenance.
  if (overlayKey === "timing[].ms") {
    const tid = timingIdAt(doc, path);
    const help = tid === null ? undefined : caps?.timingHelp?.[tid];
    if (tid !== null) {
      title = tid;
      kicker = help?.wireKey ? `milliseconds · START ${help.wireKey}` : "milliseconds";
    }
    if (help?.note) body.unshift(help.note);
  }

  // An outcome class: what the class MEANS, which `outcomeClasses` cannot say.
  const cls = outcomeClassAt(overlayKey, path);
  if (cls !== null) {
    const help = caps?.outcomeHelp?.[cls];
    kicker = `outcome · ${cls}`;
    if (help?.note) body.push(help.note);
  }

  // The VALUE's own prose, where a registry has some.
  if (typeof value === "string" && value !== "") {
    if (meta.widget === "channel") {
      const reg = (schema.channels ?? {}) as ChannelRegistry;
      const channel = reg.channels?.[value];
      if (channel) {
        kicker = `${value} · pin ${channel.index}`;
        if (channel.rationale) body.push(channel.rationale);
        const kindDoc = reg.kinds?.[channel.kind]?.doc;
        if (kindDoc) body.push(kindDoc);
      }
    } else if (meta.widget === "strobe") {
      const reg = (schema.strobes ?? {}) as StrobeRegistry;
      const code = reg.codes?.[value];
      if (code) {
        kicker = `${value} · code ${code.code}`;
        if (code.emitted_on) body.push(`Emitted ${code.emitted_on}.`);
        if (code.rationale) body.push(code.rationale);
      }
    }
  }

  // The group's own line, last — it is the widest statement, so it reads as
  // context rather than as the answer.
  if (group?.help) body.push(group.help);
  if (body.length === 0) {
    body.push("No note is written for this field yet.");
  }
  return { title, kicker, body: dedupe(body) };
}

/**
 * The same sentence, said once.
 *
 * A caller may already have put a source's prose into `meta.help` so the inline
 * caption can carry it — `Durations` does exactly that with the template's
 * timing note — and then this module reaches the same source again and says it
 * twice, once with the START token appended and once without. Comparing on
 * letters alone catches that pair, and every other near-duplicate of the same
 * shape, without either side having to know what the other did.
 */
function dedupe(lines: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of lines) {
    const key = line.toLowerCase().replace(/[^a-z0-9]/g, "");
    // A line that merely CONTAINS an earlier one is the "…(START LZD)" case.
    if (seen.has(key) || [...seen].some((s) => key.includes(s) || s.includes(key))) {
      continue;
    }
    seen.add(key);
    out.push(line);
  }
  return out;
}

/** `timing[3].ms` → the id declared at index 3. */
function timingIdAt(doc: SpecDocument, path: string): string | null {
  const match = /^timing\[(\d+)\]/.exec(path);
  if (!match) return null;
  const rows = doc["timing"];
  if (!Array.isArray(rows)) return null;
  const row = rows[Number(match[1])];
  const id = row !== null && typeof row === "object" ? (row as Record<string, unknown>)["id"] : null;
  return typeof id === "string" ? id : null;
}

/** `contingency.outcome_map.omission.delay` → `omission`. */
function outcomeClassAt(overlayKey: string, path: string): string | null {
  if (!overlayKey.startsWith("contingency.outcome_map.")) return null;
  const match = /^contingency\.outcome_map\.([a-z_]+)\./.exec(path);
  return match?.[1] ?? null;
}

/**
 * The resting subject: what this epoch is FOR.
 *
 * Written here rather than read from `BAND_LABELS`, because those are one-word
 * names for a canvas gutter and this is a sentence. Kept short — it is what an
 * operator reads once per step and then stops seeing.
 */
const EPOCH_NOTE: Record<number, string> = {
  1: "How a trial starts, and what it costs the animal to ignore one. Nothing is presented until the animal has committed, so a stimulus is never spent on an incidental beam-break.",
  2: "What the animal is shown, and how long it must stay to have sampled it. Order is the discriminandum in a sequence task — A then B is a different trial from B then A.",
  3: "Where an answer can be given and what counts as giving one. The ports come from the rig's own wiring, so this is the box talking rather than the document.",
  4: "Every way a trial can end, what each is scored as, and whether the session counter moves. There are exactly two endings; which one a class routes to is the whole question.",
};
