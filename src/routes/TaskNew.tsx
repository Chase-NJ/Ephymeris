import { parse as parseYaml } from "yaml";

import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { FieldRow } from "@/components/common/FieldRow";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { DiagnosticsPanel } from "@/components/specs/DiagnosticsPanel";
import { ParadigmCard } from "@/components/specs/ParadigmCard";
import { SpecField } from "@/components/specs/SpecField";
import { StructureBlocks } from "@/components/specs/StructureBlocks";
import { TaskJourney } from "@/components/specs/TaskJourney";
import { TaskShape } from "@/components/specs/TaskShape";
import { ChipsRow, SelectRow } from "@/components/specs/rows";
import { errorMessage } from "@/lib/cohorts/commands";
import { getRig } from "@/lib/hardware/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { springPanel, springSnappy } from "@/lib/motion";
import { getSkeleton } from "@/lib/specs/commands";
import { createSpecFrom, idError, suggestId } from "@/lib/specs/create";
import { runOp } from "@/lib/specs/operations";
import { placeDiagnostics, type PlacedDiagnostics } from "@/lib/specs/diagnostics";
import {
  getAt,
  setAt,
  timingIds,
  timingIndexOf,
  topologyOf,
} from "@/lib/specs/document";
import type {
  ChannelRegistry,
  ParadigmQuestion,
  ParadigmSummary,
  SpecCapabilities,
  SpecDocument,
  SpecGraph,
  SpecSchema,
  StrobeRegistry,
} from "@/lib/specs/types";
import { useCompile } from "@/lib/specs/useCompile";
import { useCapabilities, useParadigms, useSpecs } from "@/lib/specs/useSpecs";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";

/**
 * Design a task, one question at a time, with the machine beside you.
 *
 * THE WIZARD ALWAYS STARTS FROM A PARADIGM, and never from nothing. The
 * objection docs/specs.md used to raise — that a skeleton generator would be a
 * second definition of what a minimal legal spec is — is answered by WHERE the
 * generator lives, not by refusing to have one: `specs.skeleton` reads the
 * paradigm, the template's `capabilities()`, the channel registry and the
 * strobe vocabulary, and emits no value it did not find in one of them. A
 * "start from nothing" option would break that, because there would be no
 * paradigm to read.
 *
 * The first screen therefore asks which shape, and the answer comes back as a
 * document that already compiles — with its graph, in the same round trip, so
 * "it compiles at every step" is true from step zero.
 *
 * Structural steps apply the SAME ops the Designer's blocks do
 * (`lib/specs/operations.ts`), so there is one implementation of "what must
 * move with this knob" and the wizard cannot drift from the editor. Scalar
 * steps are plain `setAt` — layer 3 and layer 4 change no shape.
 *
 * Nothing is written until Create, which is `createSpecFrom` — the same
 * rename-and-save Duplicate uses. No new wire command for creation.
 */
/**
 * The paradigm that fixes nothing.
 *
 * Named here rather than inferred, because it is the one paradigm the wizard
 * treats structurally: it is what `/task/new` opens on and what "design from
 * scratch" returns to. Everything else about it — that it is kept out of the
 * gallery — is declared in the paradigm file as `hidden`, not decided here.
 */
const BLANK = "blank";

export function TaskNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const paradigmId = params.get("paradigm");
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const { specs, schema, unavailable } = useSpecs();

  const [step, setStep] = useState(0);
  const [doc, setDoc] = useState<SpecDocument | null>(null);
  const [base, setBase] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  /*
   * The rig's pin map, fetched once.
   *
   * READ-ONLY HERE, and deliberately not `useRig` — that hook carries an
   * editing session with a debounced preview behind it, which is the Rig wiring
   * screen's job. The wizard only wants to print which pin a channel is, so a
   * one-shot `hardware.get` is the whole need. A failure leaves the map empty
   * and the pads read "not wired", which is the truth from here.
   */
  const [pins, setPins] = useState<Record<string, number>>({});
  /* The save landed. Distinct from `creating`, which is still true while the
   * route transition plays out — see the unsaved guard below. */
  const [created, setCreated] = useState(false);

  const [id, setId] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");

  const { paradigms, loading: loadingParadigms } = useParadigms();
  const chosen = useMemo(
    () => paradigms.find((p) => p.id === (base ?? paradigmId)) ?? null,
    [paradigms, base, paradigmId],
  );
  const taken = useMemo(() => new Set(specs.map((s) => s.specId)), [specs]);

  const caps = useCapabilities(useMemo(() => topologyOf(doc), [doc]));
  const { result } = useCompile(client, connected && doc !== null, doc, id === "" ? null : id);
  const placed = useMemo(
    () => (result ? placeDiagnostics(result.diagnostics) : null),
    [result],
  );

  // Same "keep the last good picture" rule as the Designer: a mid-answer error
  // must not blank the thing the operator is deciding from.
  const [lastGood, setLastGood] = useState<SpecGraph | null>(null);
  useEffect(() => {
    if (result?.graph) setLastGood(result.graph);
  }, [result]);
  const graph = result?.graph ?? lastGood;

  /*
   * Gated on `connected`, and re-run when it flips.
   *
   * Firing this on mount alone raced the socket's auth handshake: the call
   * rejected, the catch below swallowed it, and every pad read "not wired" on a
   * rig that was wired fine. Depending on `connected` makes a reconnect the
   * retry, which is the same shape every other domain provider uses.
   */
  useEffect(() => {
    if (!connected) return;
    let live = true;
    getRig(client)
      .then((reply) => {
        if (!live) return;
        const map: Record<string, number> = {};
        const pinBlock = (reply.document as RigDocument).pins ?? {};
        for (const [name, pin] of Object.entries(pinBlock)) {
          if (typeof pin?.index === "number") map[name] = pin.index;
        }
        setPins(map);
      })
      .catch(() => {
        /* Pads read "not wired"; nothing here is worth interrupting a design for. */
      });
    return () => {
      live = false;
    };
  }, [client, connected]);

  /*
   * An in-progress DESIGN is unsaved work; a design that has been created is
   * not. Guarding on `doc !== null` alone kept the wizard armed after its own
   * successful save, so the first navigation afterwards asked whether to
   * discard a task that was already on disk — and answering "keep editing"
   * stranded the operator on a screen whose Create button says "Creating…".
   */
  useRegisterUnsaved("spec-wizard", doc !== null && !created);

  /**
   * Start from a paradigm.
   *
   * ONE ROUND TRIP, and the compile comes back with it — so the canvas has a
   * graph before the first question is answered rather than after it. This
   * replaces a loop that replayed structural ops client-side against the BASE
   * spec's capabilities, with a comment explaining why that was a limitation:
   * the generator runs where `capabilities()` actually lives, so there is no
   * limitation to explain.
   */
  async function start(id_: string) {
    setLoadError(null);
    try {
      const suggested = suggestId(id_ === BLANK ? "task" : id_, taken);
      const reply = await getSkeleton(client, id_, suggested, {});
      setBase(id_);
      setDoc(parseYaml(reply.text) as SpecDocument);
      setId(suggested);
      setStep(1);
      setShowTemplates(false);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

  /*
   * FROM SCRATCH IS THE DEFAULT, so the wizard opens on step 1 rather than on a
   * picker. `?paradigm=` still works — that is what the Task tab's template
   * cards navigate to — and choosing a template later goes through the very
   * same `start()`, so there is one code path either way.
   *
   * Guarded on `doc === null` rather than a mounted ref: the effect must not
   * fire again after the operator switches templates, and the document is the
   * honest record of whether a start has happened.
   */
  useEffect(() => {
    if (!connected || doc !== null || loadingParadigms) return;
    if (paradigms.length === 0) return;
    void start(paradigmId ?? BLANK);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, doc, loadingParadigms, paradigms.length, paradigmId]);

  async function create() {
    if (!doc || id === "" || idError(id, taken)) return;
    setCreating(true);
    try {
      await createSpecFrom(client, doc, {
        id,
        label,
        description,
        // A task designed here reproduces no sketch and derives from no
        // variant; leaving either claim in place would make TG231's severity
        // key on something untrue.
        clearProvenance: true,
      });
      setCreated(true);
      navigate(`/task/designer/${id}`);
    } catch (err) {
      setLoadError(errorMessage(err));
      setCreating(false);
    }
  }

  if (unavailable) {
    return (
      <Shell>
        <div
          className="surface mx-auto mt-8 max-w-2xl rounded-md px-4 py-3.5 text-[12px] leading-relaxed"
          style={{ color: "var(--color-status-warning)" }}
        >
          {unavailable}
        </div>
      </Shell>
    );
  }

  /*
   * The questions step exists only if the paradigm asks something.
   *
   * `blank` — the from-scratch default, and so the step list most operators
   * ever see — declares `questions: []` on purpose: a shape that fixes nothing
   * leaves nothing open to ask about. Keeping the step and explaining the
   * emptiness put a screen with no controls on it in the middle of the default
   * path. Six steps from scratch, seven from a template that asks.
   */
  const asks = (chosen?.questions ?? []).length > 0;
  const steps =
    doc === null ? [] : STEPS.filter((s) => s.kind !== "questions" || asks);
  const current = steps[step - 1] ?? null;

  /*
   * The rail's step list, and the walk's one hint line.
   *
   * Review is a star like any other rather than an "and then you're done"
   * afterthought — it is a place the operator stands, with its own decision
   * (create, or go back), so it gets a position on the map.
   */
  const onReview = step > steps.length;
  const journey = [...steps.map((s) => s.star), "Review"];
  const hint = onReview
    ? result?.ok
      ? "Everything compiles. Creating it opens the Designer, where every value is still editable."
      : "Not compiling yet — the panel below says what is unresolved."
    : (current?.hint ?? "");

  return (
    <Shell>
      <section className="pointer-events-auto mx-auto max-w-3xl px-8 py-8">
        <div className="mb-2 flex items-center gap-2">
          <Button variant="ghost" onClick={() => navigate("/task")} title="Back to Task">
            <ArrowLeft size={13} strokeWidth={1.75} />
          </Button>
          <span className="font-mono text-[10px] text-static/70">
            {base === null
              ? "starting"
              : `${onReview ? "review" : `${step} of ${steps.length}`} · ${chosen?.name ?? base}`}
          </span>

          {/* Compiles-at-every-step, as a line rather than a diagram. The graph
              used to sit beside these questions to make the claim watchable;
              the graph now belongs to the Designer (that is the whole split),
              so what survives here is the fact itself. */}
          {result?.table && (
            <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-static">
              <Check size={10} strokeWidth={2} style={{ color: "var(--color-status-ok)" }} />
              {result.table.nNodes} states · {result.table.nEdges} edges
            </span>
          )}
          {result && !result.ok && (
            <span
              className="ml-auto font-mono text-[10px]"
              style={{ color: "var(--color-status-error)" }}
            >
              {result.diagnostics.filter((d) => d.severity === "ERROR").length} error
            </span>
          )}
        </div>

        {doc !== null && !showTemplates && (
          <TaskJourney
            labels={journey}
            active={Math.min(step - 1, journey.length - 1)}
            hint={hint}
            settled={onReview}
          />
        )}

        <div className="flex items-baseline justify-between gap-3">
          <h1 className="font-display text-[22px] text-starlight">Design a task</h1>
          {/* The template path, one quiet click away rather than in front of
              every new task. */}
          {doc !== null && !showTemplates && step <= 2 && (
            <Button variant="ghost" onClick={() => setShowTemplates(true)}>
              Start from a template
            </Button>
          )}
        </div>

        {loadError && (
          <p className="mt-3 text-[11px]" style={{ color: "var(--color-status-error)" }}>
            {loadError}
          </p>
        )}

        {showTemplates ? (
          <StartingPoints
            paradigms={paradigms}
            loading={loadingParadigms}
            onPick={(pid) => void start(pid)}
            onCancel={() => setShowTemplates(false)}
          />
        ) : doc === null ? (
          <p className="mt-8 text-[12px] text-static">
            {loadError ? "" : "Starting a task…"}
          </p>
        ) : (
          <>
            {/* THE SUBJECT, ABOVE THE QUESTION ABOUT IT. Every step edits some
                corner of this, so it stays on screen for all of them — and the
                epoch the current step touches is lit, which is what connects a
                question to the part of the task it changes. */}
            <div className="mt-5">
              <TaskShape
                doc={doc}
                pins={pins}
                focus={current?.kind === "epoch" ? current.band : null}
                onChange={setDoc}
              />
            </div>

            {/*
             * The entering step animates; the leaving one just goes.
             *
             * This was `AnimatePresence mode="wait"` first, which holds the NEW
             * child unmounted until the old one's exit animation reports done —
             * and here it never did, so the rail advanced while the panel stayed
             * frozen on step one. A cross-fade is not worth a dependency on an
             * exit lifecycle completing; keying on `step` gives React a fresh
             * node to slide in, which is the whole visible effect.
             */}
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={springPanel}
              className="mt-4"
            >
              <div className="hud rounded-md px-4 py-3.5">
                <div className="font-display text-[15px] text-starlight">
                  {current?.title ?? "Ready to create"}
                </div>
                <p className="mt-1 max-w-[62ch] text-[11.5px] leading-relaxed text-static">
                  {current?.blurb ??
                    "Nothing is written until you create it, and everything stays editable afterwards."}
                </p>

                <div className="mt-3.5 flex flex-col gap-3">
                  {current?.kind === "identity" && (
                    <div className="flex flex-col gap-1.5">
                      <FieldRow
                        label="Id"
                        help="Names the file, the compiled table, and what a board reports after an upload."
                        type="string"
                        value={id}
                        fallback=""
                        baseline=""
                        error={idError(id, taken) ?? undefined}
                        onChange={(next) => setId(String(next ?? ""))}
                      />
                      <FieldRow
                        label="Label"
                        type="string"
                        value={label}
                        fallback=""
                        baseline=""
                        mono={false}
                        onChange={(next) => setLabel(String(next ?? ""))}
                      />
                      <FieldRow
                        label="Description"
                        type="string"
                        value={description}
                        fallback=""
                        baseline=""
                        mono={false}
                        onChange={(next) => setDescription(String(next ?? ""))}
                      />
                    </div>
                  )}

                  {current?.kind === "epoch" && schema && (
                    <EpochStep
                      band={current.band}
                      doc={doc}
                      graph={graph}
                      caps={caps}
                      schema={schema}
                      placed={placed}
                      pins={pins}
                      onChange={setDoc}
                    />
                  )}

                  {/* The paradigm's own questions, rendered from what the sidecar
                  declared. Each `path` is a document path the schema knows, so an
                  answer is a set on a validated location and never new structure —
                  which is what lets a paradigm file stay declarative. */}
                  {current?.kind === "questions" && schema && (
                    <div className="flex flex-col gap-1.5">
                      {(chosen?.questions ?? []).map((q) => (
                        <ParadigmQuestionRow
                          key={q.id}
                          question={q}
                          doc={doc}
                          schema={schema}
                          placed={placed}
                          onChange={(value) => setDoc(setAt(doc, q.path, value))}
                        />
                      ))}
                    </div>
                  )}

                  {current?.kind === "session" && schema && (
                    <>
                      <div className="flex flex-col gap-1.5">
                        {POLICY_FIELDS.map(({ path, overlayKey }) => {
                          const meta = schema.overlay.fields[overlayKey];
                          if (!meta) return null;
                          return (
                            <SpecField
                              key={path}
                              path={path}
                              overlayKey={overlayKey}
                              meta={meta}
                              value={getAt(doc, path)}
                              baseline={getAt(doc, path)}
                              schema={schema}
                              doc={doc}
                              placed={placed}
                              onChange={(next) => setDoc(setAt(doc, path, next))}
                            />
                          );
                        })}
                      </div>
                      <RampStep
                        doc={doc}
                        caps={caps}
                        schema={schema}
                        placed={placed}
                        onChange={setDoc}
                      />
                    </>
                  )}

                  {current === null && (
                    <p className="text-[11.5px] leading-relaxed text-static">
                      {result?.table
                        ? `${result.table.nNodes} states, ${result.table.nEdges} edges, ${result.table.sizeBytes} bytes.`
                        : "The spec has to compile before it can be created."}
                      {/* Not while creating: the save lands in the library
                      before the route changes, so the id this screen is about
                      becomes "taken" by its own success and flashed as an
                      error. */}
                      {!creating && idError(id, taken) && (
                        <span
                          className="mt-1 block"
                          style={{ color: "var(--color-status-error)" }}
                        >
                          {idError(id, taken)}
                        </span>
                      )}
                    </p>
                  )}
                </div>
              </div>
            </motion.div>

            {/* When a step leaves the spec not compiling, the reason has to be
            on this screen. Without it the only signal is an error count in the
            corner, which tells the operator that something is wrong and nothing
            about what. */}
            {result && !result.ok && (
              <div className="mt-3">
                <DiagnosticsPanel diagnostics={result.diagnostics} />
              </div>
            )}

            <div className="mt-5 flex items-center justify-between gap-2">
              <Button
                variant="ghost"
                disabled={step <= 1}
                onClick={() => setStep((s) => Math.max(1, s - 1))}
              >
                <ArrowLeft size={12} strokeWidth={1.75} />
                Back
              </Button>
              {!onReview ? (
                <Button
                  variant="primary"
                  /*
                   * Gated only where a step has a precondition the NEXT step
                   * depends on, which today is exactly one: the id names the
                   * file, so walking six screens with a duplicate or malformed
                   * one and finding out at Create is six screens of wasted
                   * work. Every other step is answerable in any order and
                   * disabling Next on those would be a guess about what the
                   * operator is done thinking about.
                   */
                  disabled={
                    current?.kind === "identity" &&
                    (id === "" || idError(id, taken) !== null)
                  }
                  // Clamped: without it the counter runs past the last step
                  // and reads "11 of 7" on the review screen.
                  onClick={() => setStep((s) => Math.min(steps.length + 1, s + 1))}
                >
                  Next
                  <ArrowRight size={12} strokeWidth={1.75} />
                </Button>
              ) : (
                <Button
                  variant="primary"
                  disabled={
                    creating ||
                    id === "" ||
                    idError(id, taken) !== null ||
                    !result?.ok ||
                    !connected
                  }
                  onClick={() => void create()}
                >
                  {creating ? "Creating…" : "Create task"}
                </Button>
              )}
            </div>
          </>
        )}
      </section>
    </Shell>
  );
}

type Step = { star: string; title: string; blurb: string; hint: string } & (
  | { kind: "identity" }
  | { kind: "questions" }
  | { kind: "epoch"; band: number }
  | { kind: "session" }
);

/**
 * The questions, in the order a task is actually thought about: what the
 * animal senses, what it must do to earn the stimulus, how it answers, what
 * counts as right — then the numbers, which change no shape.
 */
/**
 * SEVEN STEPS, IN THE ORDER A TRIAL HAPPENS.
 *
 * The nine this replaces were ordered by LAYER, which is how the document is
 * ordered and how the compiler consumes it — topology, then contingency, then
 * timing, then policy. That put "how long is the engagement window" (step 8) and
 * "does a trial begin with a commitment hold" (step 4) on different screens,
 * four apart, describing the same half-second of the same trial.
 *
 * The wizard's order is the OPERATOR'S mental model; the document's layer order
 * is the compiler's. Nothing requires them to match, because every field here is
 * a path write — the document comes out in exactly the same shape either way.
 *
 * RESPONSES COME BEFORE STIMULI, inverting what the old order did. A trial type
 * maps a stimulus onto a target, so the answer space has to exist before
 * anything can be mapped onto it; asking "which port is correct for odour A"
 * before the ports exist is asking about a set that is still empty.
 */
const STEPS: Step[] = [
  {
    kind: "identity",
    star: "Name",
    hint: "Give it an id — that names the file, the compiled table, and what a board reports back.",
    title: "What is it called?",
    blurb:
      "The id names the file and the compiled table; the label and description are what the library shows.",
  },
  {
    kind: "questions",
    star: "Shape",
    hint: "This template leaves a few choices open. Answer them and the rest follows.",
    title: "What does this paradigm need to know?",
    blurb:
      "The choices this shape leaves open. Everything else already has a working value.",
  },
  {
    kind: "epoch",
    band: 1,
    star: "Begin",
    hint: "Decide what counts as the animal committing to a trial, and what abstaining costs.",
    title: "How does a trial begin?",
    blurb:
      "The animal has to commit before a stimulus is spent. A commitment hold is " +
      "what separates an incidental beam-break from a real initiation — and these " +
      "are the durations of that opening, including what an abstention costs.",
  },
  {
    kind: "epoch",
    band: 3,
    star: "Answer",
    hint: "Set up the answer space first — the stimuli on the next step get mapped onto it.",
    title: "How does it answer?",
    blurb:
      "Choose between ports, or withhold entirely — and how long the window stays " +
      "open, how long a poke must hold, and how much fluid a correct one delivers. " +
      "This comes before the stimuli because a trial type maps one onto the other.",
  },
  {
    kind: "epoch",
    band: 2,
    star: "Sample",
    hint: "Add what can be presented, then say which port each one means.",
    title: "What does the animal sample?",
    blurb:
      "Stimuli are what you can present; stages are how many must be sampled in " +
      "sequence before answering. The map above is where their order is changed.",
  },
  {
    kind: "epoch",
    band: 4,
    star: "Score",
    hint: "Every way a trial can end, what it is scored as, and what it costs.",
    title: "What counts as right?",
    blurb:
      "Every way a trial can end, what each one is scored as, and what the data " +
      "file records. Rewarding adds the delivery and consumption states through " +
      "each port's own line.",
  },
  {
    kind: "session",
    star: "Run",
    hint: "How trials are drawn, how many there are, and which durations ramp.",
    title: "How does the session run?",
    blurb:
      "Trial selection, how many, the seed — and the ramp, if this task gets " +
      "harder as it goes. None of this changes the machine.",
  },
];

const POLICY_FIELDS = [
  { path: "policy.selection.mode", overlayKey: "policy.selection.mode" },
  { path: "policy.n_trials", overlayKey: "policy.n_trials" },
  { path: "policy.seed", overlayKey: "policy.seed" },
];

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
function EpochStep({
  band,
  doc,
  graph,
  caps,
  schema,
  placed,
  pins,
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
  onChange: (next: SpecDocument) => void;
}) {
  const ids = useMemo(() => timingIdsForBand(doc, graph, band), [doc, graph, band]);

  return (
    <div className="flex flex-col gap-3">
      <StructureBlocks
        band={band}
        doc={doc}
        baseline={doc}
        caps={caps}
        schema={schema}
        placed={placed}
        onChange={onChange}
      />

      {band === 3 && <PortPads doc={doc} pins={pins} />}
      <EpochTimeline graph={graph} band={band} />

      {ids.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
          <div className="font-mono text-[10px] tracking-wider text-static uppercase">
            How long
          </div>
          {ids.map((tid) => {
            const index = timingIndexOf(doc, tid);
            const meta = schema.overlay.fields["timing[].ms"];
            if (index < 0 || !meta) return null;
            return (
              <SpecField
                key={tid}
                path={`timing[${index}].ms`}
                overlayKey="timing[].ms"
                meta={{ ...meta, label: tid }}
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
      )}
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
function timingIdsForBand(
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
function spineOf(graph: SpecGraph | null, band: number) {
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
function EpochTimeline({ graph, band }: { graph: SpecGraph | null; band: number }) {
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
function fmtMs(ms: number): string {
  if (ms >= 10000) return `${Math.round(ms / 1000)}s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

/**
 * The live response ports, each with the hardware it actually drives.
 *
 * This is the seam the Rig wiring screen exists for: the wizard names channels
 * and the rig says which pin each one is, so a pad shows both and the operator
 * never has to hold the mapping in their head while deciding what a correct
 * answer is. The pin comes from `hardware.get` — if the rig has no entry for a
 * channel the pad says so rather than inventing one, which is the same failure
 * TG226 reports at compile.
 */
function PortPads({ doc, pins }: { doc: SpecDocument; pins: Record<string, number> }) {
  const ports = Object.entries(portsOf(doc));
  if (ports.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
      <div className="font-mono text-[10px] tracking-wider text-static uppercase">
        Where it can answer
      </div>
      <div
        className="grid gap-1.5"
        style={{ gridTemplateColumns: `repeat(${Math.min(ports.length, 2)}, minmax(0, 1fr))` }}
      >
        {ports.map(([name, binding]) => {
          const channel = String(binding["channel"] ?? name);
          const reward = binding["reward_line"];
          const pin = pins[channel];
          const rewardPin = typeof reward === "string" ? pins[reward] : undefined;
          return (
            <div key={name} className="rounded-[3px] border border-halo px-2 py-1.5">
              <div className="truncate font-mono text-[11px] text-starlight">{name}</div>
              <div className="mt-0.5 font-mono text-[9.5px] text-static">
                {channel} · {pin === undefined ? "not wired" : `pin ${pin}`}
              </div>
              <div className="font-mono text-[9.5px] text-static">
                {typeof reward === "string"
                  ? `${reward} · ${rewardPin === undefined ? "not wired" : `pin ${rewardPin}`}`
                  : "no reward"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function portsOf(doc: SpecDocument): Record<string, Record<string, unknown>> {
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


/**
 * The template picker, which is now the SECONDARY path.
 *
 * `/task/new` opens straight into step 1 on the `blank` paradigm; this screen
 * is reached by a quiet "start from a template instead" link. That inverts what
 * it used to be — a mandatory gate in front of every new task — and the reason
 * is that a template is a shortcut for the seven shapes this lab already runs,
 * not a prerequisite for designing an eighth.
 *
 * The doctrine survives the inversion intact: "from scratch" is a paradigm that
 * FIXES nothing (`paradigms/blank.yaml`), not the absence of one. The generator
 * still reads every value from an authority, `specs.skeleton` is unchanged, and
 * there is still exactly one creation path.
 */
function StartingPoints({
  paradigms,
  loading,
  onPick,
  onCancel,
}: {
  paradigms: ParadigmSummary[];
  loading: boolean;
  onPick: (paradigmId: string) => void;
  onCancel: () => void;
}) {
  // `hidden` rather than an id check: `blank` is what you get by NOT picking,
  // so listing it here would offer the default as one of the alternatives.
  const shown = paradigms.filter((p) => !p.hidden);

  return (
    <div className="scrollbar-none flex-1 overflow-y-auto px-6 py-5">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-display text-[15px] text-starlight">
            Start from a template
          </h2>
          <Button variant="ghost" onClick={onCancel}>
            Design from scratch instead
          </Button>
        </div>
        <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-static">
          Seven shapes this lab already runs. Picking one fills in the answers it
          implies — you can still change every one of them in the steps that follow.
        </p>

        {loading ? (
          <p className="mt-4 text-[12px] text-static">Reading the templates…</p>
        ) : shown.length === 0 ? (
          <p className="mt-4 text-[12px] text-static">
            No templates are installed, which means the compiler's registry did not
            ship. Designing from scratch still works.
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {shown.map((paradigm) => (
              <ParadigmCard
                key={paradigm.id}
                paradigm={paradigm}
                onClick={() => onPick(paradigm.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The guided-setup shell, shared with the session flow by intent.
 *
 * `SessionConfig` and `SessionMapping` are the same shape — a centred column
 * floating over the rig's own sky — and designing a task is the same kind of
 * errand: a short walk with a known end. The wizard used to be a two-pane
 * editor instead, canvas left and rail right, which made it look like the
 * Designer and read like an editor you had to already understand.
 *
 * `pointer-events-none` on the scroller so the sky behind stays orbitable where
 * the column does not cover it; the column takes the pointer back.
 * `scrollbar-none` because the scrollbar would otherwise consume 10px of the
 * column and shift everything in it off centre (`index.css`).
 */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative h-full">
      <SkyBackdrop />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit: between two sky routes the shell stops fading the
        // page (`AppShell`), so anything that should fade has to say so.
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        {children}
      </motion.div>
    </div>
  );
}

/**
 * One paradigm question, rendered by the same overlay the form uses.
 *
 * `source` says where the options come from, and every one of them is a
 * registry the compiler validates against — so a picker here cannot offer a
 * value the compile then rejects. `value` is free entry, and falls through to
 * the overlay's own widget for the path.
 */
function ParadigmQuestionRow({
  question,
  doc,
  schema,
  placed,
  onChange,
}: {
  question: ParadigmQuestion;
  doc: SpecDocument;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (value: unknown) => void;
}) {
  const current = getAt(doc, question.path);

  const options = useMemo(() => {
    const channels = (schema.channels ?? {}) as {
      channels?: Record<string, { kind: string; index: number }>;
    };
    switch (question.source) {
      case "channel":
        return Object.entries(channels.channels ?? {})
          .filter(([, c]) => !question.kind || c.kind === question.kind)
          .map(([name, c]) => ({ value: name, label: `${name} (pin ${c.index})` }));
      case "stimulus": {
        const stimuli = (doc["contingency"] as { stimuli?: Array<{ id?: string }> })?.stimuli;
        return (stimuli ?? []).map((s) => ({ value: String(s.id), label: String(s.id) }));
      }
      case "trial_type": {
        const tt = (doc["contingency"] as { trial_types?: Array<{ id?: string }> })
          ?.trial_types;
        return (tt ?? []).map((t) => ({ value: String(t.id), label: String(t.id) }));
      }
      case "strobe":
        return Object.keys(
          ((schema.strobes ?? {}) as { codes?: Record<string, unknown> }).codes ?? {},
        ).map((n) => ({ value: n, label: n }));
      default:
        return null;
    }
  }, [question, doc, schema]);

  if (options !== null) {
    return (
      <SelectRow
        label={question.label}
        help={question.help ?? undefined}
        value={typeof current === "string" ? current : null}
        baseline={null}
        options={options}
        error={
          question.required && (current === null || current === undefined)
            ? "This paradigm needs an answer here."
            : undefined
        }
        onChange={onChange}
      />
    );
  }

  const meta = schema.overlay.fields[overlayKeyFor(question.path)];
  if (meta) {
    return (
      <SpecField
        path={question.path}
        overlayKey={overlayKeyFor(question.path)}
        meta={{ ...meta, label: question.label, ...(question.help ? { help: question.help } : {}) }}
        value={current}
        baseline={current}
        schema={schema}
        doc={doc}
        placed={placed}
        onChange={onChange}
      />
    );
  }
  return (
    <FieldRow
      label={question.label}
      help={question.help ?? undefined}
      type={typeof current === "number" ? "int" : "string"}
      value={current}
      fallback={current ?? ""}
      baseline={current}
      onChange={onChange}
    />
  );
}

/** `contingency.stimuli[0].emitter` → `contingency.stimuli[].emitter`. */
function overlayKeyFor(path: string): string {
  return path.replace(/\[\d+\]/g, "[]").replace(/\.[a-z0-9_]+\.(?=[a-z_]+$)/i, ".*.");
}

/**
 * The shaping ramp, as two questions rather than a nested array.
 *
 * WHICH durations move, then WHEN they move. Splitting it that way is what
 * makes the invariant enforceable: every row has to carry every ramped id,
 * because the firmware rewrites the whole set at a boundary and a row that
 * omits one does not leave it alone — it reverts to whatever the row before
 * left. Editing a raw array of objects would make that trap reachable in one
 * keystroke; here it is unreachable, because the ops fill the rows.
 */
/**
 * The trial a stage row takes over at.
 *
 * COMMITS ON BLUR, not per keystroke, and that is not a preference. The op
 * re-sorts the schedule so the document is never out of order — which means a
 * row physically moves as its number changes, remounting the input. Committing
 * per keystroke made "100" impossible to type: after the `1` the row sorted to
 * the front and took the focus with it.
 */
function StageTrialInput({
  index,
  value,
  onCommit,
}: {
  index: number;
  value: number;
  onCommit: (at: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  // The document is the authority — an op elsewhere (adding a row, removing
  // one) can move this row's number without the input being touched.
  useEffect(() => setDraft(String(value)), [value]);

  function commit() {
    const n = Number(draft);
    if (draft.trim() === "" || !Number.isInteger(n) || n < 0) {
      setDraft(String(value));
      return;
    }
    if (n !== value) onCommit(n);
  }

  return (
    <label className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] whitespace-nowrap text-static">from trial</span>
      <input
        aria-label={`Stage ${index + 1} starts at trial`}
        className="w-16 rounded-sm border border-halo bg-nebula px-1.5 py-0.5 font-mono text-[10px] text-starlight"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setDraft(String(value));
        }}
      />
    </label>
  );
}

function RampStep({
  doc,
  caps,
  schema,
  placed,
  onChange,
}: {
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const rows = useMemo(() => {
    const raw = (doc["policy"] as { stage_schedule?: unknown })?.stage_schedule;
    return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
  }, [doc]);

  const rampable = useMemo(
    () =>
      (Array.isArray(doc["timing"]) ? (doc["timing"] as Array<Record<string, unknown>>) : [])
        .map((r) => String(r["id"]))
        .filter((id) => id !== "t_zero" && id !== "t_poll_interval"),
    [doc],
  );

  const ramped = useMemo(() => {
    const seen = new Set<string>();
    for (const row of rows) {
      for (const id of Object.keys((row["set"] as Record<string, unknown>) ?? {})) {
        seen.add(id);
      }
    }
    return rampable.filter((id) => seen.has(id));
  }, [rows, rampable]);

  const ctx = {
    doc,
    caps: caps ?? EMPTY_CAPS,
    next: caps ?? EMPTY_CAPS,
    channels: (schema.channels ?? {}) as ChannelRegistry,
    strobes: (schema.strobes ?? {}) as StrobeRegistry,
  };

  return (
    <div className="flex flex-col gap-2">
      <ChipsRow
        label="Durations that ramp"
        help="Chosen once and carried by every row — a row that omits one reverts it."
        values={ramped}
        baseline={[]}
        options={rampable.map((id) => ({ value: id, label: id }))}
        onChange={(ids) => onChange(runOp(ctx, { op: "setRampedIds", ids }, {}).doc)}
      />

      {ramped.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
          <div className="font-mono text-[10px] tracking-wider text-static uppercase">
            Stages
          </div>
          {rows.length === 0 && (
            <p className="text-[10px] text-static/70">No stages yet.</p>
          )}
          {rows.map((row, i) => (
            <div key={i} className="flex flex-col gap-1 border-t border-halo pt-1.5 first:border-0">
              <div className="flex items-center justify-between gap-2">
                {/*
                 * `at_trial` IS EDITABLE, and it has to be. The step's own blurb
                 * promises "which durations move, then the trials they move at";
                 * seeding a row and then rendering its trial number as static
                 * text delivers half of that. The seeded spacing is a guess at a
                 * schedule, not the schedule — the lab's real shaping ramp
                 * switches at 0/20/25/50/100, which the even spacing never hits.
                 *
                 * The op re-sorts on every edit, so typing a number that lands a
                 * row out of order fixes the order rather than tripping TG205 —
                 * which does not fail, it applies the wrong row.
                 */}
                <StageTrialInput
                  index={i}
                  value={Number(row["at_trial"]) || 0}
                  onCommit={(at) =>
                    onChange(runOp(ctx, { op: "setStageTrial", index: i }, { at_trial: at }).doc)
                  }
                />
                <Button
                  variant="ghost"
                  onClick={() =>
                    onChange(runOp(ctx, { op: "removeStageRow", index: i }, {}).doc)
                  }
                >
                  Remove
                </Button>
              </div>
              {ramped.map((id) => {
                const path = `policy.stage_schedule[${i}].set.${id}`;
                const meta = schema.overlay.fields["timing[].ms"];
                if (!meta) return null;
                return (
                  <SpecField
                    key={id}
                    path={path}
                    overlayKey="timing[].ms"
                    meta={{ ...meta, label: id }}
                    value={getAt(doc, path)}
                    baseline={getAt(doc, path)}
                    schema={schema}
                    doc={doc}
                    placed={placed}
                    onChange={(next) => onChange(setAt(doc, path, next))}
                  />
                );
              })}
            </div>
          ))}
          <Button
            variant="ghost"
            onClick={() => onChange(runOp(ctx, { op: "addStageRow" }, {}).doc)}
          >
            Add a stage
          </Button>
        </div>
      )}
    </div>
  );
}

//: A stand-in while `capabilities()` is in flight. The ramp ops read neither
//: field — they touch layer 4 only — so this cannot change what they produce.
const EMPTY_CAPS: SpecCapabilities = {
  outcomeClasses: [],
  requiredTiming: [],
  knobs: [],
  template: "four_epoch",
  templateVersion: 2,
};
