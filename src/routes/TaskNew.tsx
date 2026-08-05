import { parse as parseYaml } from "yaml";

import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { DiagnosticsPanel } from "@/components/specs/DiagnosticsPanel";
import { ExplainProvider, ExplainTile } from "@/components/specs/ExplainTile";
import { TaskJourney } from "@/components/specs/TaskJourney";
import { EpochStep } from "@/components/specs/steps/EpochStep";
import { IdentityStep } from "@/components/specs/steps/IdentityStep";
import { ParadigmStep } from "@/components/specs/steps/ParadigmStep";
import { ReviewStep } from "@/components/specs/steps/ReviewStep";
import { SessionStep } from "@/components/specs/steps/SessionStep";
import { StartingPoints } from "@/components/specs/steps/StartingPoints";
import { errorMessage } from "@/lib/cohorts/commands";
import { getRig } from "@/lib/hardware/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { springPanel } from "@/lib/motion";
import { getSkeleton } from "@/lib/specs/commands";
import { createSpecFrom, idError, suggestId } from "@/lib/specs/create";
import { placeDiagnostics } from "@/lib/specs/diagnostics";
import { topologyOf } from "@/lib/specs/document";
import type { SpecDocument, SpecGraph } from "@/lib/specs/types";
import { useCompile } from "@/lib/specs/useCompile";
import { useCapabilities, useParadigms, useSpecs } from "@/lib/specs/useSpecs";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";

/**
 * Design a task, one question at a time.
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
 * Structural steps apply the SAME ops the Designer's blocks do
 * (`lib/specs/operations.ts`), so there is one implementation of "what must
 * move with this knob" and the wizard cannot drift from the editor. Scalar
 * steps are plain `setAt` — layer 3 and layer 4 change no shape.
 *
 * Nothing is written until Create, which is `createSpecFrom` — the same
 * rename-and-save Duplicate uses. No new wire command for creation.
 *
 * THIS FILE OWNS THE WALK, NOT THE STEPS. State, the live compile, `start()`
 * and `create()`, and the step list live here; every step's body is a component
 * under `components/specs/steps/`. The split is not cosmetic — the epoch steps
 * grew a live graph, a drag surface and an explanation rail, and a route that
 * also rendered them would be the only place any of it could be read.
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
  const idProblem = idError(id, taken);

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
  /* Showing a picture the current document did not produce. Derived from both
   * halves rather than from its own effect: `lastGood` is set in an effect and
   * therefore lags a render, so a separate flag would disagree with the graph
   * it describes for one frame. */
  const staleGraph = !result?.graph && lastGood !== null;

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
   * ONE ROUND TRIP, and the compile comes back with it — so the wizard has a
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
    if (!doc || id === "" || idProblem) return;
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
  const steps = doc === null ? [] : STEPS.filter((s) => s.kind !== "questions" || asks);
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
  /*
   * One readout per star — what that step has produced so far. This is what
   * `TaskShape`'s four epoch cards became, attached to the star they describe
   * rather than standing in a tile of their own above every step.
   *
   * DELIBERATELY NOT `bandReadouts`, which is the canvas gutter's caption and
   * answers a different question — what SHAPE the epoch is, in a column 130px
   * wide. A star has 72px of pitch (`CONNECTOR` + the star), so this answers
   * "what has this step produced" in a count, which fits. Longer forms ran into
   * each other and read as one smeared line.
   */
  const sublabels = [...steps.map(starReadout), starReadout(null)];

  function starReadout(s: Step | null): string | null {
    if (s === null) return result?.table ? `${result.table.sizeBytes} B` : null;
    const knobs = topologyOf(doc) ?? {};
    switch (s.kind) {
      case "epoch":
        switch (s.band) {
          case 1:
            return knobs["commit_hold"] === false ? "no hold" : "hold on";
          case 2: {
            const n = knobs["n_sampling_stages"];
            return typeof n === "number" ? `${n} stage${n === 1 ? "" : "s"}` : null;
          }
          case 3: {
            if (knobs["response_mode"] === "go_nogo") return "withhold";
            const ports = Array.isArray(knobs["response_ports"])
              ? knobs["response_ports"].length
              : 0;
            return `${ports} port${ports === 1 ? "" : "s"}`;
          }
          default:
            return caps ? `${caps.outcomeClasses.length} outcomes` : null;
        }
      case "session": {
        const n = (doc?.["policy"] as { n_trials?: unknown } | undefined)?.n_trials;
        return typeof n === "number" ? `${n} trials` : null;
      }
      default:
        return null;
    }
  }
  const hint = onReview
    ? result?.ok
      ? "Everything compiles. Creating it opens the Designer, where every value is still editable."
      : "Not compiling yet — the panel below says what is unresolved."
    : (current?.hint ?? "");

  const canAdvance = current?.kind !== "identity" || (id !== "" && idProblem === null);

  return (
    <ExplainProvider>
    <Shell>
      {/* WIDER THAN max-w-3xl, because the epoch steps are two columns now —
          the explanation tile left, the questions right. `TaskJourney` is fixed
          width and centred, so widening the section moves nothing about it. */}
      <section
        className="pointer-events-auto mx-auto max-w-5xl px-8 py-8"
        /*
         * Enter advances, from a text field on any step but the last.
         *
         * The identity step is three text boxes and a Next button, and every
         * operator who has ever filled in a form tries Enter there. It is
         * scoped to text inputs so it cannot fire from a select or a chip, and
         * gated on `canAdvance` so it obeys exactly the same rule the button
         * does — Enter must never do something the disabled button would not.
         */
        onKeyDown={(e) => {
          if (e.key !== "Enter" || onReview || !canAdvance) return;
          const el = e.target as HTMLElement;
          if (el.tagName !== "INPUT" || (el as HTMLInputElement).type === "checkbox") return;
          e.preventDefault();
          setStep((s) => Math.min(steps.length + 1, s + 1));
        }}
      >
        <div className="mb-2 flex items-center gap-2">
          <Button variant="ghost" onClick={() => navigate("/task")} title="Back to Task">
            <ArrowLeft size={13} strokeWidth={1.75} />
          </Button>
          <span className="font-mono text-[10px] text-static/70">
            {base === null
              ? "starting"
              : `${onReview ? "review" : `${step} of ${steps.length}`} · ${chosen?.name ?? base}`}
          </span>

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
            sublabels={sublabels}
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
              /*
               * TWO COLUMNS ON THE EPOCH STEPS ONLY.
               *
               * Identity, the paradigm's questions, the session policy and
               * Review carry few enough fields that a second column would sit
               * empty most of the time — and an explanation rail that is blank
               * on four screens out of seven reads as a bug rather than as a
               * feature that has nothing to say. The epoch steps are where the
               * firmware-named tunables are.
               */
              className={
                current?.kind === "epoch"
                  ? "mt-5 lg:grid lg:grid-cols-[216px_minmax(0,1fr)] lg:items-start lg:gap-4"
                  : // A step with three fields in a 1024px column puts its
                    // inputs a hand's width from their labels. The wider
                    // section is for the epoch steps' second column; everything
                    // else keeps the measure it was laid out at.
                    "mt-5 max-w-3xl"
              }
            >
              {current?.kind === "epoch" && schema && (
                <ExplainTile doc={doc} caps={caps} schema={schema} band={current.band} />
              )}
              <div className="hud rounded-md px-4 py-3.5 max-lg:mt-3">
                <div className="font-display text-[15px] text-starlight">
                  {current?.title ?? "Ready to create"}
                </div>
                <p className="mt-1 max-w-[62ch] text-[11.5px] leading-relaxed text-static">
                  {current?.blurb ??
                    "Nothing is written until you create it, and everything stays editable afterwards."}
                </p>

                <div className="mt-3.5 flex flex-col gap-3">
                  {current?.kind === "identity" && (
                    <IdentityStep
                      id={id}
                      label={label}
                      description={description}
                      idError={idProblem ?? undefined}
                      onId={setId}
                      onLabel={setLabel}
                      onDescription={setDescription}
                    />
                  )}

                  {current?.kind === "questions" && schema && (
                    <ParadigmStep
                      questions={chosen?.questions ?? []}
                      doc={doc}
                      schema={schema}
                      placed={placed}
                      onChange={setDoc}
                    />
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
                      stale={staleGraph}
                      onChange={setDoc}
                    />
                  )}

                  {current?.kind === "session" && schema && (
                    <SessionStep
                      doc={doc}
                      caps={caps}
                      schema={schema}
                      placed={placed}
                      suggestedRamp={chosen?.ramped ?? []}
                      onChange={setDoc}
                    />
                  )}

                  {current === null && (
                    <ReviewStep
                      table={result?.table}
                      idError={idProblem}
                      creating={creating}
                    />
                  )}
                </div>
              </div>
            </motion.div>

            {/* When a step leaves the spec not compiling, the reason has to be
            on this screen. Without it the only signal is an error count in the
            corner, which tells the operator that something is wrong and nothing
            about what. */}
            {result && !result.ok && (
              <div className={current?.kind === "epoch" ? "mt-3 lg:ml-[232px]" : "mt-3 max-w-3xl"}>
                <DiagnosticsPanel diagnostics={result.diagnostics} />
              </div>
            )}

            {/* Aligned under the questions column, not under the explanation
                rail — Next belongs to the thing being answered. */}
            <div
              className={
                current?.kind === "epoch"
                  ? "mt-5 flex items-center justify-between gap-2 lg:ml-[232px]"
                  : "mt-5 flex max-w-3xl items-center justify-between gap-2"
              }
            >
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
                  disabled={!canAdvance}
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
                    creating || id === "" || idProblem !== null || !result?.ok || !connected
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
    </ExplainProvider>
  );
}

type Step = { star: string; title: string; blurb: string; hint: string } & (
  | { kind: "identity" }
  | { kind: "questions" }
  | { kind: "epoch"; band: number }
  | { kind: "session" }
);

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
 * STIMULI NOW COME BEFORE RESPONSES, inverting what this comment used to argue.
 * The old order put Answer before Sample on the grounds that "a trial type maps
 * a stimulus onto a target, so the answer space has to exist before anything can
 * be mapped onto it". That premise moved: mapping is now a DRAG of a stimulus
 * chip onto a response tile (`ResponseMap`), so the stimuli are the things that
 * have to exist first, and the ports do not — they come from the rig's channel
 * registry rather than from the document, and are available on the Answer step
 * whatever order the walk runs in.
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
    band: 2,
    star: "Sample",
    hint: "Declare what can be presented — the next step maps each one onto a port.",
    title: "What does the animal sample?",
    blurb:
      "Stimuli are what you can present; stages are how many must be sampled in " +
      "sequence before answering. Which port each one means is the next step — " +
      "the stimuli have to exist before anything can be mapped onto them.",
  },
  {
    kind: "epoch",
    band: 3,
    star: "Answer",
    hint: "Pick the ports the animal can answer at, then drag each stimulus onto the one it means.",
    title: "How does it answer?",
    blurb:
      "Choose between ports, or withhold entirely — and how long the window stays " +
      "open, how long a poke must hold, and how much fluid a correct one delivers. " +
      "Dragging a stimulus onto a port is what creates a trial type.",
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
