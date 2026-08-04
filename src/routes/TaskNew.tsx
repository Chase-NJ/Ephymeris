import { parse as parseYaml } from "yaml";

import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { FieldRow } from "@/components/common/FieldRow";
import { RowDensityContext } from "@/components/common/rowDensity";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { DiagnosticsPanel } from "@/components/specs/DiagnosticsPanel";
import { SpecCanvas } from "@/components/specs/SpecCanvas";
import { SpecField } from "@/components/specs/SpecField";
import { StructureBlocks } from "@/components/specs/StructureBlocks";
import { ChipsRow, SelectRow } from "@/components/specs/rows";
import { errorMessage } from "@/lib/cohorts/commands";
import { springPanel } from "@/lib/motion";
import { getSkeleton } from "@/lib/specs/commands";
import { createSpecFrom, idError, suggestId } from "@/lib/specs/create";
import { runOp } from "@/lib/specs/operations";
import { placeDiagnostics, type PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt, topologyOf } from "@/lib/specs/document";
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
  const [selection, setSelection] = useState<Parameters<typeof SpecCanvas>[0]["selection"]>(null);

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

  useRegisterUnsaved("spec-wizard", doc !== null);

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
      const suggested = suggestId(id_, taken);
      const reply = await getSkeleton(client, id_, suggested, {});
      setBase(id_);
      setDoc(parseYaml(reply.text) as SpecDocument);
      setId(suggested);
      setStep(1);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

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

  const steps = doc === null ? [] : STEPS;
  const current = steps[step - 1] ?? null;

  return (
    <Shell>
      <header className="flex shrink-0 items-center gap-3 border-b border-halo px-4 py-2.5">
        <Button variant="ghost" onClick={() => navigate("/task")} title="Back to Task">
          <ArrowLeft size={13} strokeWidth={1.75} />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="font-display text-[14px] text-starlight">Design a task</div>
          <div className="font-mono text-[9.5px] text-static/70">
            {base === null
              ? "pick a starting point"
              : `${step > steps.length ? "review" : `${step} of ${steps.length}`} · ${chosen?.name ?? base}`}
          </div>
        </div>
        {result?.table && (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-static">
            <Check size={10} strokeWidth={2} style={{ color: "var(--color-status-ok)" }} />
            {result.table.nNodes} states · {result.table.nEdges} edges
          </span>
        )}
        {result && !result.ok && (
          <span className="font-mono text-[10px]" style={{ color: "var(--color-status-error)" }}>
            {result.diagnostics.filter((d) => d.severity === "ERROR").length} error
          </span>
        )}
      </header>

      {loadError && (
        <p
          className="shrink-0 border-b border-halo px-4 py-2 text-[11px]"
          style={{ color: "var(--color-status-error)" }}
        >
          {loadError}
        </p>
      )}

      {doc === null ? (
        <StartingPoints
          paradigms={paradigms}
          loading={loadingParadigms}
          onPick={(pid) => void start(pid)}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* The machine, beside the questions — so "it compiles at every step"
          is something the operator watches rather than something we claim. */}
          <div className="flex min-w-0 flex-1 flex-col">
            {graph ? (
              <SpecCanvas
                graph={graph}
                placed={placed}
                selection={selection}
                onSelect={setSelection}
                lit={EMPTY}
                stale={!result?.graph}
                bandReadouts={bandReadouts(topologyOf(doc))}
              />
            ) : (
              <p className="m-auto max-w-sm px-6 text-center text-[12px] leading-relaxed text-static">
                Compiling…
              </p>
            )}
          </div>

          <RowDensityContext.Provider value="stacked">
            <aside className="scrollbar-none flex w-[380px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-halo px-4 py-3">
              <div>
                <div className="font-display text-[13px] text-starlight">
                  {current?.title ?? "Review"}
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-static">
                  {current?.blurb ?? "Name it and create."}
                </p>
              </div>

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

              {current?.kind === "structure" && schema && (
                <StructureBlocks
                  band={current.band}
                  doc={doc}
                  baseline={doc}
                  caps={caps}
                  schema={schema}
                  placed={placed}
                  onChange={setDoc}
                />
              )}

              {/* The paradigm's own questions, rendered from what the sidecar
              declared. Each `path` is a document path the schema knows, so an
              answer is a set on a validated location and never new structure —
              which is what lets a paradigm file stay declarative. */}
              {current?.kind === "questions" && schema && (
                <div className="flex flex-col gap-1.5">
                  {(chosen?.questions ?? []).length === 0 ? (
                    <p className="text-[11px] leading-relaxed text-static/70">
                      This paradigm asks nothing — every choice it makes is part of
                      the shape. You can still change any of it in the steps that
                      follow.
                    </p>
                  ) : (
                    (chosen?.questions ?? []).map((q) => (
                      <ParadigmQuestionRow
                        key={q.id}
                        question={q}
                        doc={doc}
                        schema={schema}
                        placed={placed}
                        onChange={(value) => setDoc(setAt(doc, q.path, value))}
                      />
                    ))
                  )}
                </div>
              )}

              {current?.kind === "ramp" && schema && (
                <RampStep
                  doc={doc}
                  caps={caps}
                  schema={schema}
                  placed={placed}
                  onChange={setDoc}
                />
              )}

              {current?.kind === "timing" && schema && caps && (
                <div className="flex flex-col gap-1.5">
                  {caps.requiredTiming.map((tid) => {
                    const index = timingIndexOf(doc, tid);
                    if (index < 0) return null;
                    const meta = schema.overlay.fields["timing[].ms"];
                    if (!meta) return null;
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
                        onChange={(next) =>
                          setDoc(setAt(doc, `timing[${index}].ms`, next))
                        }
                      />
                    );
                  })}
                </div>
              )}

              {current?.kind === "policy" && schema && (
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
              )}

              {current === null && (
                <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
                  <div className="font-mono text-[10px] tracking-wider text-static uppercase">
                    Ready
                  </div>
                  <p className="text-[11px] leading-relaxed text-static">
                    {result?.table
                      ? `${result.table.nNodes} states, ${result.table.nEdges} edges, ${result.table.sizeBytes} bytes. Saving opens it in the Designer, where every value is still editable.`
                      : "The spec has to compile before it can be created."}
                  </p>
                  {/* Not while creating: the save lands in the library before
                  the route changes, so the id this screen is about becomes
                  "taken" by its own success and flashed as an error. */}
                  {!creating && idError(id, taken) && (
                    <p className="text-[11px]" style={{ color: "var(--color-status-error)" }}>
                      {idError(id, taken)}
                    </p>
                  )}
                </div>
              )}

              {/* When a step leaves the spec not compiling, the reason has to
              be on this screen. Without it the only signal is a dimmed graph
              and an error count in the header, which tells the operator that
              something is wrong and nothing about what. */}
              {result && !result.ok && (
                <div className="mt-2">
                  <DiagnosticsPanel diagnostics={result.diagnostics} />
                </div>
              )}

              <div className="mt-auto flex items-center justify-between gap-2 border-t border-halo pt-2">
                <Button
                  variant="ghost"
                  disabled={step <= 1}
                  onClick={() => setStep((s) => Math.max(1, s - 1))}
                >
                  <ArrowLeft size={12} strokeWidth={1.75} />
                  Back
                </Button>
                {step <= steps.length ? (
                  <Button
                    variant="primary"
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
            </aside>
          </RowDensityContext.Provider>
        </div>
      )}
    </Shell>
  );
}

const EMPTY: ReadonlySet<number> = new Set();

type Step =
  | { kind: "identity"; title: string; blurb: string }
  | { kind: "structure"; band: number; title: string; blurb: string }
  | { kind: "questions"; title: string; blurb: string }
  | { kind: "ramp"; title: string; blurb: string }
  | { kind: "timing"; title: string; blurb: string }
  | { kind: "policy"; title: string; blurb: string };

/**
 * The questions, in the order a task is actually thought about: what the
 * animal senses, what it must do to earn the stimulus, how it answers, what
 * counts as right — then the numbers, which change no shape.
 */
const STEPS: Step[] = [
  {
    kind: "identity",
    title: "What is it called?",
    blurb:
      "The id names the file and the compiled table; the label and description are what the library shows.",
  },
  {
    kind: "questions",
    title: "What does this paradigm need to know?",
    blurb:
      "The choices this shape leaves open — which lines carry the stimuli, which " +
      "port is being shaped toward. Everything else already has a working value.",
  },
  {
    kind: "structure",
    band: 2,
    title: "What does the animal sample?",
    blurb:
      "Stimuli are the things you can present; stages are how many it must sample in sequence before answering.",
  },
  {
    kind: "structure",
    band: 1,
    title: "How does a trial begin?",
    blurb:
      "A commitment hold separates an incidental beam-break from a real initiation, before any stimulus is spent.",
  },
  {
    kind: "structure",
    band: 3,
    title: "How does it answer?",
    blurb:
      "Choose between ports, or withhold entirely. Trial types are the stimulus-to-answer mappings the pool draws from.",
  },
  {
    kind: "structure",
    band: 4,
    title: "What does a correct trial get?",
    blurb: "Rewarding adds the delivery and consumption states through each port's own line.",
  },
  {
    kind: "ramp",
    title: "Does it get harder over the session?",
    blurb:
      "A stage schedule rewrites durations at trial boundaries — the shaping ramp. " +
      "Choose which durations move, then the trials they move at. A task that does " +
      "not ramp leaves this empty.",
  },
  {
    kind: "timing",
    title: "How long is everything?",
    blurb:
      "Every duration this shape requires, in the order the template asks for them. None of these change the machine — only how long it dwells.",
  },
  {
    kind: "policy",
    title: "How does the session run?",
    blurb: "Trial selection, how many trials, and the seed.",
  },
];

const POLICY_FIELDS = [
  { path: "policy.selection.mode", overlayKey: "policy.selection.mode" },
  { path: "policy.n_trials", overlayKey: "policy.n_trials" },
  { path: "policy.seed", overlayKey: "policy.seed" },
];

function timingIndexOf(doc: SpecDocument, id: string): number {
  const timing = doc["timing"];
  if (!Array.isArray(timing)) return -1;
  return timing.findIndex(
    (row) =>
      row !== null && typeof row === "object" && (row as Record<string, unknown>)["id"] === id,
  );
}

/** Same readouts the Designer shows — one line per band from the knobs. */
function bandReadouts(knobs: Record<string, unknown> | null): Record<number, string> {
  const k = knobs ?? {};
  const stages = typeof k["n_sampling_stages"] === "number" ? k["n_sampling_stages"] : null;
  const ports = Array.isArray(k["response_ports"]) ? k["response_ports"].length : 0;
  return {
    1: k["commit_hold"] === false ? "no commitment hold" : "commitment hold on",
    2:
      stages === 0
        ? "epoch skipped"
        : `${stages ?? "?"} stage${stages === 1 ? "" : "s"}` +
          (stages !== null && stages > 1 ? ` + ${stages - 1} gap` : "") +
          (k["retention_delay"] === true ? " + retention" : ""),
    3: `${k["response_mode"] === "go_nogo" ? "go / no-go" : "n-alternative"} · ${ports} port${
      ports === 1 ? "" : "s"
    }`,
    4: "",
  };
}

function StartingPoints({
  paradigms,
  loading,
  onPick,
}: {
  paradigms: ParadigmSummary[];
  loading: boolean;
  onPick: (paradigmId: string) => void;
}) {
  return (
    <div className="scrollbar-none flex-1 overflow-y-auto px-6 py-5">
      <div className="mx-auto max-w-3xl">
        <h2 className="font-display text-[15px] text-starlight">Pick a shape</h2>
        <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-static">
          A paradigm is the shape of an experiment — what the animal senses, how it
          answers, what counts as correct. Picking one gives you a working task
          immediately; every question after this changes it, and the machine is
          drawn beside you the whole way.
        </p>

        {loading ? (
          <p className="mt-4 text-[12px] text-static">Reading the paradigms…</p>
        ) : paradigms.length === 0 ? (
          <p className="mt-4 text-[12px] text-static">
            No paradigms are installed, which means the compiler's registry did not
            ship. Nothing here will work until that is fixed.
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {paradigms.map((paradigm) => (
              <button
                key={paradigm.id}
                type="button"
                onClick={() => onPick(paradigm.id)}
                className="min-w-0 rounded-sm border border-halo px-3 py-2.5 text-left transition-colors hover:border-pulsar"
              >
                <div className="text-[12.5px] text-starlight">{paradigm.name}</div>
                <div className="truncate font-mono text-[9.5px] text-static/70">
                  {paradigm.id} · {paradigm.template} v{paradigm.templateVersion}
                </div>
                <p className="mt-1.5 text-[11px] leading-relaxed text-static">
                  {paradigm.affords}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative h-full">
      <SkyBackdrop opacity={0} />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="absolute inset-0 flex flex-col"
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
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-starlight">
                  from trial {String(row["at_trial"] ?? 0)}
                </span>
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
