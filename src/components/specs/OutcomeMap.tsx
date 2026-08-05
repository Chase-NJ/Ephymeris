import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";

import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt, topologyOf } from "@/lib/specs/document";
import type { LayoutScope } from "@/lib/specs/layout";
import { outcomeRoutes, outcomeScope, type OutcomeRoute } from "@/lib/specs/outcome";
import type {
  SpecCapabilities,
  SpecDocument,
  SpecGraph,
  SpecSchema,
} from "@/lib/specs/types";
import { useCapabilities } from "@/lib/specs/useSpecs";
import { EpochGraph } from "./EpochGraph";
import { SpecField } from "./SpecField";

/**
 * Every way a trial can end, and where each one lands.
 *
 * THE TWO TERMINALS ARE THE SUBJECT. A trial ADVANCES or it REPEATS, and those
 * are the only two things that can happen to the counter — so the picture is
 * every outcome class routed into one of two sinks, and the cards below are how
 * each route is tuned. The step used to be a single "reward on correct" toggle
 * over a list of durations, which said nothing about what a trial was worth.
 *
 * WHY THIS IS NOT AN EPOCH SLICE. `EpochGraph` is asked for an explicit NODE
 * set, not for band 4, because band 4 is not the outcome epoch: the template
 * stamps a class's nodes with whatever band was current when the class was
 * first referenced, so `TRIAL_REPEAT` is in band 1 and `TRIAL_ADVANCE` in band
 * 3 on an ordinary 2AFC — and a go/no-go task has no band 4 whatsoever.
 * `lib/specs/outcome.ts` does the walk; see its header.
 *
 * WHAT AN OPERATOR CAN AND CANNOT DO HERE. They cannot add a terminal — there
 * are two and the interpreter knows only those — and they cannot invent an
 * outcome class either, because `capabilities(topology)` decides which exist
 * and TG302 errors in both directions. What they CAN do is retune every class
 * that exists, and see which ones a different shape would produce, named with
 * the knob that would produce it. A class this topology cannot make is shown
 * greyed rather than hidden, for the same reason a stale timing row is: hiding
 * it silently answers a question the operator was about to ask.
 */
export function OutcomeMap({
  doc,
  graph,
  caps,
  schema,
  placed,
  stale,
  onChange,
}: {
  doc: SpecDocument;
  graph: SpecGraph | null;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  stale: boolean;
  onChange: (next: SpecDocument) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);

  const routes = useMemo(() => (graph ? outcomeRoutes(graph) : []), [graph]);
  const scope = useMemo<LayoutScope>(
    () => ({ kind: "nodes", nodes: graph ? outcomeScope(graph) : new Set<number>() }),
    [graph],
  );

  const knobs = topologyOf(doc) ?? {};
  const goNoGo = knobs["response_mode"] === "go_nogo";

  /*
   * WHAT A DIFFERENT SHAPE WOULD PRODUCE, asked rather than derived.
   *
   * These are two real `specs.capabilities` calls against proposed topologies,
   * the same thing `useOperation` does before running a structural block. The
   * alternative is re-implementing `capabilities()`'s conditionals in TS, which
   * is a second answer to "which classes exist" and exactly the drift the
   * function-not-a-table rule exists to prevent.
   */
  const flippedMode = useMemo(
    () => ({ ...knobs, response_mode: goNoGo ? "n_alternative" : "go_nogo" }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(knobs), goNoGo],
  );
  const withHold = useMemo(
    () => ({ ...knobs, commit_hold: true }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(knobs)],
  );
  const modeCaps = useCapabilities(flippedMode);
  const holdCaps = useCapabilities(withHold);

  const have = new Set(caps?.outcomeClasses ?? []);
  const unlockable: Array<{ cls: string; how: string }> = [];
  for (const cls of modeCaps?.outcomeClasses ?? []) {
    if (!have.has(cls)) {
      unlockable.push({
        cls,
        how: goNoGo
          ? "appears in n-alternative choice — switch the response mode on the Answer step"
          : "appears in go/no-go — switch the response mode on the Answer step",
      });
    }
  }
  for (const cls of holdCaps?.outcomeClasses ?? []) {
    if (!have.has(cls) && !unlockable.some((u) => u.cls === cls)) {
      unlockable.push({
        cls,
        how: "appears once a trial has a hold to break — turn the commitment hold on, or add a sampling stage",
      });
    }
  }

  const advance = routes.filter((r) => r.terminalKind === "advance");
  const repeat = routes.filter((r) => r.terminalKind === "repeat");

  return (
    <div className="flex flex-col gap-3">
      <EpochGraph
        graph={graph}
        scope={scope}
        stale={stale}
        placed={placed}
        emptyNote="Nothing scores yet — the machine has no outcome to route until it compiles."
      />

      {/* THE TWO SINKS. Everything a trial can do lands in one of them, and
      which one is the fact that decides whether the session counter moves. */}
      <div className="grid gap-1.5 sm:grid-cols-2">
        <Sink
          title="Trial advances"
          note="Counted, and the session moves on. A correct trial also clears the penalty escalator."
          routes={advance}
          doc={doc}
          caps={caps}
          schema={schema}
          placed={placed}
          open={open}
          onOpen={setOpen}
          onChange={onChange}
        />
        <Sink
          title="Trial repeats"
          note="Re-presented, and the counter does not move. An invalid trial carries no evidence about discrimination, so counting it would bias the session."
          routes={repeat}
          doc={doc}
          caps={caps}
          schema={schema}
          placed={placed}
          open={open}
          onOpen={setOpen}
          onChange={onChange}
        />
      </div>

      {unlockable.length > 0 && (
        <div className="flex flex-col gap-1 rounded-sm border border-halo px-2.5 py-2 opacity-70">
          <div className="font-mono text-[10px] tracking-wider text-static uppercase">
            This shape does not produce
          </div>
          {unlockable.map(({ cls, how }) => (
            <div key={cls} className="text-[10.5px] leading-relaxed text-static">
              <span className="font-mono text-static/80">{cls}</span> — {how}.
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** One terminal, and every class that routes into it. */
function Sink({
  title,
  note,
  routes,
  doc,
  caps,
  schema,
  placed,
  open,
  onOpen,
  onChange,
}: {
  title: string;
  note: string;
  routes: OutcomeRoute[];
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  open: string | null;
  onOpen: (cls: string | null) => void;
  onChange: (next: SpecDocument) => void;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-[3px] border border-halo px-2 py-1.5">
      <div>
        <div className="font-mono text-[10.5px] text-starlight">{title}</div>
        <p className="mt-0.5 text-[10px] leading-relaxed text-static/80">{note}</p>
      </div>
      {routes.length === 0 ? (
        <span className="text-[10px] text-static/60">nothing ends here</span>
      ) : (
        routes.map((route) => (
          <OutcomeCard
            key={route.cls}
            route={route}
            doc={doc}
            caps={caps}
            schema={schema}
            placed={placed}
            open={open === route.cls}
            onOpen={() => onOpen(open === route.cls ? null : route.cls)}
            onChange={onChange}
          />
        ))
      )}
    </div>
  );
}

/**
 * One outcome class, expanding to its own parameters.
 *
 * The explanation is `capabilities().outcomeHelp[cls].note` — the template's
 * own sentence about what the class MEANS ("no stimulus was presented, so the
 * trial carries no evidence about discrimination"). `outcomeClasses` says only
 * that a class exists; this is the only place its meaning is written down, and
 * it now rides on the wire so a form can say it.
 */
function OutcomeCard({
  route,
  doc,
  caps,
  schema,
  placed,
  open,
  onOpen,
  onChange,
}: {
  route: OutcomeRoute;
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  open: boolean;
  onOpen: () => void;
  onChange: (next: SpecDocument) => void;
}) {
  const still = useReduceMotion();
  const help = caps?.outcomeHelp?.[route.cls];
  const base = `contingency.outcome_map.${route.cls}`;
  const escalated =
    getAt(doc, "policy.penalty_escalation.applies_to") === route.cls;

  return (
    <div
      className="rounded-[3px] border transition-colors"
      style={{ borderColor: open ? "var(--color-pulsar)" : "var(--color-halo)" }}
    >
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-baseline justify-between gap-2 px-2 py-1 text-left"
      >
        <span
          className="min-w-0 truncate font-mono text-[10.5px]"
          style={{ color: open ? "var(--color-starlight)" : "var(--color-static)" }}
        >
          {route.cls}
        </span>
        <span className="shrink-0 font-mono text-[9px] text-static/70">
          {escalated && "escalates · "}
          {route.correctionEdge !== null && "correctable · "}
          {String(getAt(doc, `${base}.delay`) ?? "")}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={still ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={still ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={still ? { duration: 0 } : springSnappy}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-1.5 px-2 pb-2">
              {help?.note && (
                <p className="text-[10px] leading-relaxed text-static/80">{help.note}</p>
              )}
              {OUTCOME_FIELDS.map((field) => (
                <Row
                  key={field}
                  path={`${base}.${field}`}
                  overlayKey={`contingency.outcome_map.*.${field}`}
                  {...{ doc, schema, placed, onChange }}
                />
              ))}
              {/*
               * The correction budget, ONLY where the block already exists.
               *
               * Rendering an input for a `policy.correction.budgets` a task has
               * not declared would invite writing one — and a budgets map that
               * covers some ports is worse than one covering none, because the
               * missing entry reads as a deliberate zero rather than as an
               * unstated default. `operations.ts` maintains the same rule from
               * the other side.
               */}
              {route.correctionEdge !== null &&
                budgetPorts(doc).map((port) => (
                  <Row
                    key={port}
                    path={`policy.correction.budgets.${port}`}
                    overlayKey="policy.correction.budgets.*"
                    label={`correction budget · ${port}`}
                    {...{ doc, schema, placed, onChange }}
                  />
                ))}
              {escalated &&
                ESCALATION_FIELDS.map((field) => (
                  <Row
                    key={field}
                    path={`policy.penalty_escalation.${field}`}
                    overlayKey={`policy.penalty_escalation.${field}`}
                    {...{ doc, schema, placed, onChange }}
                  />
                ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** In the order the operator asks about them, not the schema's. */
const OUTCOME_FIELDS = ["terminal", "delay", "strobe", "reward", "trigger"];
const ESCALATION_FIELDS = ["step_ms", "ceiling_ms", "clears_on"];

/** The ports a correction budget is declared for; empty when the block is not
 * there at all, which is what keeps this from inventing one. */
function budgetPorts(doc: SpecDocument): string[] {
  const budgets = getAt(doc, "policy.correction.budgets");
  return budgets !== null && typeof budgets === "object" && !Array.isArray(budgets)
    ? Object.keys(budgets as Record<string, unknown>)
    : [];
}

function Row({
  path,
  overlayKey,
  label,
  doc,
  schema,
  placed,
  onChange,
}: {
  path: string;
  overlayKey: string;
  label?: string;
  doc: SpecDocument;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const meta = schema.overlay.fields[overlayKey];
  if (!meta) return null;
  // An absent key is a declaration in itself — `reward: null` omits the whole
  // delivery path — so a field the document does not carry is not offered as a
  // blank input that invites filling in.
  if (getAt(doc, path) === undefined) return null;
  return (
    <SpecField
      path={path}
      overlayKey={overlayKey}
      meta={label ? { ...meta, label } : meta}
      value={getAt(doc, path)}
      baseline={getAt(doc, path)}
      schema={schema}
      doc={doc}
      placed={placed}
      onChange={(next) => onChange(setAt(doc, path, next))}
    />
  );
}
