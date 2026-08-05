import { motion } from "framer-motion";
import { useMemo } from "react";

import { springSnappy } from "@/lib/motion";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt, timingIds, timingIndexOf } from "@/lib/specs/document";
import type {
  SpecCapabilities,
  SpecDocument,
  SpecGraph,
  SpecSchema,
} from "@/lib/specs/types";
import type { LayoutScope } from "@/lib/specs/layout";
import { EpochGraph } from "../EpochGraph";
import { OutcomeMap } from "../OutcomeMap";
import { ResponseMap } from "../ResponseMap";
import { SpecField } from "../SpecField";
import { StructureBlocks } from "../StructureBlocks";

/**
 * One epoch: what it does, and how long it takes.
 *
 * THE TIMINGS ARE DERIVED FROM THE GRAPH, not from a table mapping ids to
 * epochs. Every compiled node carries its band and the timing id it dwells on,
 * so "which durations belong to the response epoch" is a question the compiler
 * has already answered — and a table here would be a second answer that drifts
 * the first time a template moves a node.
 *
 * It also gets the grouping RIGHT in a way a hand-written table would not have.
 * The no-engage penalty lands in Engagement rather than Outcomes, because that
 * is the epoch it aborts from; the wrong-port penalty lands in Response. Asked
 * cold, nobody would file them there — but "how long does an abstention cost"
 * genuinely belongs beside "how long is the engagement window".
 *
 * Two durations no node dwells on are added by hand, because they are reached
 * through layer 2 rather than by the graph: a port's `reward_duration` (the
 * reward PULSE binds `@trial.reward`, so its index is runtime-resolved) and an
 * outcome's `delay` where the outcome's own node sits in another band.
 */
/** What `ResponseMap`'s tiles already are, so the blocks do not repeat them. */
const WIRED_BY_RESPONSE_MAP = [
  "addResponseOption",
  "removeResponseOption",
  "addTrialType",
] as const;

export function EpochStep({
  band,
  doc,
  graph,
  caps,
  schema,
  placed,
  pins,
  stale,
  onChange,
}: {
  band: number;
  doc: SpecDocument;
  graph: SpecGraph | null;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  /** Channel name → pin index, from the rig. Empty until `hardware.get` lands. */
  pins: Record<string, number>;
  /** `graph` is the last one that compiled, not the current document's. */
  stale: boolean;
  onChange: (next: SpecDocument) => void;
}) {
  const ids = useMemo(() => timingIdsForBand(doc, graph, band), [doc, graph, band]);
  // Memoised because `EpochGraph`'s layout memo keys on it — a fresh object
  // every render would recompute the picture on every keystroke elsewhere.
  const scope = useMemo<LayoutScope>(() => ({ kind: "band", band }), [band]);

  /*
   * BAND 4 IS NOT THE OUTCOME EPOCH, so the Score step is its own surface.
   *
   * The template stamps a class's nodes with whatever band was current when
   * that class was first referenced, so both terminals live outside band 4 on
   * every task — and a go/no-go task has no band 4 at all. `OutcomeMap` scopes
   * by the derived outcome node set instead, and carries its own picture.
   */
  if (band === 4) {
    return (
      <div className="flex flex-col gap-3">
        <OutcomeMap
          doc={doc}
          graph={graph}
          caps={caps}
          schema={schema}
          placed={placed}
          stale={stale}
          onChange={onChange}
        />
        <StructureBlocks
          band={band}
          doc={doc}
          baseline={doc}
          caps={caps}
          schema={schema}
          placed={placed}
          covered={[]}
          onChange={onChange}
        />
        <Durations {...{ ids, doc, caps, schema, placed, onChange }} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* THE MACHINE, BUT ONLY THIS EPOCH'S PART OF IT, above the questions
          that change it. */}
      <EpochGraph graph={graph} scope={scope} stale={stale} placed={placed} />

      <StructureBlocks
        band={band}
        doc={doc}
        baseline={doc}
        caps={caps}
        schema={schema}
        placed={placed}
        // `ResponseMap` below IS these three, as gestures on the tiles.
        covered={band === 3 ? WIRED_BY_RESPONSE_MAP : []}
        onChange={onChange}
      />

      {band === 3 && (
        <ResponseMap
          doc={doc}
          caps={caps}
          schema={schema}
          placed={placed}
          pins={pins}
          onChange={onChange}
        />
      )}
      <EpochTimeline graph={graph} band={band} />

      <Durations {...{ ids, doc, caps, schema, placed, onChange }} />
    </div>
  );
}

/**
 * The durations one epoch owns, each explained by the template's own note.
 *
 * `timing[].ms`'s overlay help describes the FIELD — the uint16 ceiling and the
 * sentinel — which is one true sentence repeated verbatim down a list of six
 * rows, so it stops being read. The template's `timing_defaults` note describes
 * THIS id ("odorPokeHold at BehaviorBox.h:1176 — the pre-odor commitment
 * hold"), which is the only place a duration's meaning is written down and is
 * different on every row. It rides on `capabilities()` precisely so a form can
 * say it; where the template has no note (a per-port reward duration, which the
 * ops create rather than the template), the overlay's own line stands in.
 */
function Durations({
  ids,
  doc,
  caps,
  schema,
  placed,
  onChange,
}: {
  ids: string[];
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  if (ids.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
      <div className="font-mono text-[10px] tracking-wider text-static uppercase">
        How long
      </div>
      {ids.map((tid) => {
        const index = timingIndexOf(doc, tid);
        const meta = schema.overlay.fields["timing[].ms"];
        if (index < 0 || !meta) return null;
        const note = caps?.timingHelp?.[tid]?.note;
        const wireKey = caps?.timingHelp?.[tid]?.wireKey;
        return (
          <SpecField
            key={tid}
            path={`timing[${index}].ms`}
            overlayKey="timing[].ms"
            meta={{
              ...meta,
              label: tid,
              ...(note ? { help: wireKey ? `${note} (START ${wireKey})` : note } : {}),
            }}
            value={getAt(doc, `timing[${index}].ms`)}
            baseline={getAt(doc, `timing[${index}].ms`)}
            schema={schema}
            doc={doc}
            placed={placed}
            onChange={(next) => onChange(setAt(doc, `timing[${index}].ms`, next))}
          />
        );
      })}
    </div>
  );
}

/**
 * The timing ids this epoch owns, in the document's vector order.
 *
 * Vector order rather than node order, because the vector index is what the
 * listing prints and what a ramp row keys on — two places an operator will see
 * these ids again.
 */
export function timingIdsForBand(
  doc: SpecDocument,
  graph: SpecGraph | null,
  band: number,
): string[] {
  const mine = new Set<string>();
  for (const node of graph?.nodes ?? []) {
    if (node.band === band && node.durationId) mine.add(node.durationId);
  }

  // Reward volume: the PULSE binds `@trial.reward`, so the node carries no
  // static duration id and only the port binding knows which row it is.
  if (band === 3) {
    for (const binding of Object.values(portsOf(doc))) {
      const id = binding["reward_duration"];
      if (typeof id === "string") mine.add(id);
    }
  }

  // `t_zero` is structural — the zero-duration nodes that carry a paired
  // strobe's second half (D2) and the response branch guard (D3). Offering it
  // as an editable number invites someone to make it non-zero, which breaks
  // the pairing model rather than lengthening anything.
  mine.delete("t_zero");
  // The poll interval is the whole rig's input granularity, not one epoch's.
  mine.delete("t_poll_interval");

  return timingIds(doc).filter((id) => mine.has(id));
}

/**
 * The success edge out of each node primitive.
 *
 * A HOLD is held, a WAIT_ENTRY is entered, a DELAY expires. Everything else a
 * node can do — BROKEN, or a WAIT_ENTRY's TIMEOUT — is the animal failing the
 * state, which leaves the epoch rather than continuing through it.
 */
const SUCCESS_TRIGGER: Record<string, string | null> = {
  DELAY: "TIMEOUT",
  WAIT_ENTRY: "ENTER",
  HOLD: "HELD",
  WAIT_EXIT: "EXIT",
  PULSE: "DONE",
  TERMINAL: null,
};

/**
 * One pass through a band, in execution order.
 *
 * THE SPINE IS WALKED, NOT LISTED. A band's timing ids include its penalties,
 * and a penalty is not sequential with the window it punishes — laying every
 * duration in the band end to end would draw a trial that cannot happen, with
 * the abstention penalty following the engagement window it exists instead of.
 * So this follows the success edge from the band's first node and stops when
 * the walk leaves the band. What it visits is one clean pass; what it doesn't
 * visit is an alternative, and gets listed as one.
 */
export function spineOf(graph: SpecGraph | null, band: number) {
  if (!graph) return [];
  const byIndex = new Map(graph.nodes.map((n) => [n.index, n]));
  const first = graph.nodes
    .filter((n) => n.band === band)
    .sort((a, b) => a.index - b.index)[0];

  const spine: typeof graph.nodes = [];
  const seen = new Set<number>();
  let cur = first;
  while (cur && cur.band === band && !seen.has(cur.index)) {
    seen.add(cur.index);
    spine.push(cur);
    const trigger = SUCCESS_TRIGGER[cur.type] ?? null;
    const edge = trigger
      ? graph.edges.find((e) => e.src === cur!.index && e.trigger === trigger)
      : undefined;
    cur = edge ? byIndex.get(edge.dst) : undefined;
  }
  return spine;
}

/**
 * The band's durations drawn to scale, with what it costs to fail beneath.
 *
 * The bar is proportional but floored, so a 10 ms hold beside a 60 s window
 * stays visible and hoverable. THE NUMBER PRINTED ON EACH SEGMENT IS THE
 * AUTHORITY — the picture is for the ratio, not for reading a value off.
 */
export function EpochTimeline({
  graph,
  band,
}: {
  graph: SpecGraph | null;
  band: number;
}) {
  const { spine, alternatives } = useMemo(() => {
    const walk = spineOf(graph, band);
    const onSpine = new Set(walk.map((n) => n.index));
    return {
      spine: walk.filter((n) => (n.durationMs ?? 0) > 0),
      alternatives: (graph?.nodes ?? []).filter(
        (n) => n.band === band && !onSpine.has(n.index) && (n.durationMs ?? 0) > 0,
      ),
    };
  }, [graph, band]);

  if (spine.length < 2) return null;
  const total = spine.reduce((sum, n) => sum + (n.durationMs ?? 0), 0);

  return (
    <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-mono text-[10px] tracking-wider text-static uppercase">
          One pass
        </div>
        <div className="font-mono text-[10px] text-static">{fmtMs(total)}</div>
      </div>

      <div className="flex h-6 items-stretch gap-[2px] overflow-hidden rounded-[3px]">
        {spine.map((node, i) => (
          <motion.div
            key={node.index}
            layout
            transition={springSnappy}
            title={`${node.label} · ${node.durationMs} ms`}
            /* Wide enough for "200ms" — the floor exists so a brief state stays
               visible, and a floor that still clips the number it exists to
               show would be no floor at all. */
            className="flex min-w-[46px] items-center justify-center overflow-hidden px-1"
            style={{
              flexGrow: node.durationMs ?? 1,
              flexBasis: 0,
              backgroundColor:
                i % 2 === 0 ? "var(--color-nebula)" : "var(--color-halo)",
            }}
          >
            <span className="truncate font-mono text-[9.5px] text-starlight">
              {fmtMs(node.durationMs ?? 0)}
            </span>
          </motion.div>
        ))}
      </div>

      <div className="flex flex-wrap gap-x-2.5 gap-y-0.5">
        {spine.map((node) => (
          <span key={node.index} className="text-[9.5px] text-static">
            {node.label}
          </span>
        ))}
      </div>

      {alternatives.length > 0 && (
        <div className="mt-0.5 flex flex-wrap gap-x-2.5 gap-y-0.5 border-t border-halo pt-1.5">
          <span className="font-mono text-[9.5px] tracking-wider text-static uppercase">
            instead, on failure
          </span>
          {alternatives.map((node) => (
            <span key={node.index} className="font-mono text-[9.5px] text-static">
              {node.label} {fmtMs(node.durationMs ?? 0)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Milliseconds, in whatever unit reads as a duration rather than a count. */
export function fmtMs(ms: number): string {
  if (ms >= 10000) return `${Math.round(ms / 1000)}s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

export function portsOf(doc: SpecDocument): Record<string, Record<string, unknown>> {
  const contingency = doc["contingency"];
  const ports =
    contingency && typeof contingency === "object"
      ? (contingency as Record<string, unknown>)["ports"]
      : null;
  const out: Record<string, Record<string, unknown>> = {};
  for (const [name, value] of Object.entries((ports as object) ?? {})) {
    if (value && typeof value === "object") {
      out[name] = value as Record<string, unknown>;
    }
  }
  return out;
}
