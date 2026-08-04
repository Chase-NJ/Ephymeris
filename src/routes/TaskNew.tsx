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
import { errorMessage } from "@/lib/cohorts/commands";
import { springPanel } from "@/lib/motion";
import { getSpec } from "@/lib/specs/commands";
import { createSpecFrom, idError, suggestId } from "@/lib/specs/create";
import { placeDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt, topologyOf } from "@/lib/specs/document";
import { PARADIGMS, RECIPES } from "@/lib/specs/paradigms";
import { runOp } from "@/lib/specs/operations";
import type {
  ChannelRegistry,
  SpecDocument,
  SpecGraph,
  StrobeRegistry,
} from "@/lib/specs/types";
import { useCompile } from "@/lib/specs/useCompile";
import { useCapabilities, useSpecs } from "@/lib/specs/useSpecs";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";

/**
 * Design a task, one question at a time, with the machine beside you.
 *
 * THE WIZARD ALWAYS STARTS FROM A BUNDLED PARADIGM. It must, and this is not a
 * detail to relax later: docs/specs.md §3 argues that a blank-skeleton
 * generator would be a second definition of what a minimal legal spec is,
 * competing with the schema. Starting from a spec that already compiles means
 * every step is an EDIT — of a document the compiler and the linter already
 * agree on — rather than a construction that has to be validated into
 * existence. The moment this grows a "start from nothing" option, that
 * argument is lost.
 *
 * Structural steps apply the SAME ops the Designer's blocks do
 * (`lib/specs/operations.ts`), so there is one implementation of "what must
 * move with this knob" and the wizard cannot drift from the editor. Scalar
 * steps are plain `setAt` — layer 3 and layer 4 change no shape.
 *
 * Nothing is written until Create, which is `createSpecFrom` — the same
 * rename-and-save the gallery and Duplicate use. No new wire command.
 */
export function TaskNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const recipeId = params.get("recipe");
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

  const recipe = useMemo(() => RECIPES.find((r) => r.id === recipeId) ?? null, [recipeId]);
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

  /* Loading the base. A recipe additionally replays its steps through the real
   * ops, so a recipe cannot describe a task the editor could not also reach —
   * and each step's own suggestions fill in what it would otherwise ask. */
  async function start(specId: string, steps = recipe?.steps ?? []) {
    setLoadError(null);
    try {
      const reply = await getSpec(client, specId);
      if (!reply.raw) {
        setLoadError("That spec's YAML won't parse, so it can't be a starting point.");
        return;
      }
      let next: SpecDocument = reply.raw;
      for (const invocation of steps) {
        // Capabilities for the proposed topology are not available
        // synchronously here, so a recipe step runs against the base's own —
        // which is why RECIPES only holds steps whose reconciliation does not
        // depend on a knob that moved. Anything richer belongs in the editor,
        // where the round trip exists.
        if (caps === null) break;
        next = runOp(
          {
            doc: next,
            caps,
            next: caps,
            channels: (schema?.channels ?? {}) as ChannelRegistry,
            strobes: (schema?.strobes ?? {}) as StrobeRegistry,
          },
          invocation,
          {},
        ).doc;
      }
      setBase(specId);
      setDoc(next);
      setId(suggestId(specId, taken));
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
              : `${step > steps.length ? "review" : `${step} of ${steps.length}`} · from ${base}${
                  recipe ? ` · ${recipe.name}` : ""
                }`}
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
        <StartingPoints recipe={recipe} onPick={(specId) => void start(specId)} />
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
  recipe,
  onPick,
}: {
  recipe: { name: string; base: string; affords: string; changes: string } | null;
  onPick: (specId: string) => void;
}) {
  return (
    <div className="scrollbar-none flex-1 overflow-y-auto px-6 py-5">
      <div className="mx-auto max-w-3xl">
        {recipe ? (
          <>
            <h2 className="font-display text-[15px] text-starlight">{recipe.name}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-static">{recipe.affords}</p>
            <p className="mt-2 text-[11px] leading-relaxed text-static/80">
              Starts from <span className="font-mono text-starlight">{recipe.base}</span> and{" "}
              {recipe.changes.charAt(0).toLowerCase() + recipe.changes.slice(1)} You can change
              anything from there.
            </p>
            <div className="mt-3">
              <Button variant="primary" onClick={() => onPick(recipe.base)}>
                Begin
                <ArrowRight size={12} strokeWidth={1.75} />
              </Button>
            </div>
          </>
        ) : (
          <>
            <h2 className="font-display text-[15px] text-starlight">
              Pick a starting point
            </h2>
            <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-static">
              Every design starts from a task that already compiles — that way each
              answer is a change to a working machine rather than a step toward one
              that might not be. You can change any of it, including the shape.
            </p>
            <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {PARADIGMS.map((paradigm) => (
                <button
                  key={paradigm.id}
                  type="button"
                  onClick={() => onPick(paradigm.variants[0]!.specId)}
                  className="min-w-0 rounded-sm border border-halo px-3 py-2.5 text-left transition-colors hover:border-pulsar"
                >
                  <div className="text-[12.5px] text-starlight">{paradigm.name}</div>
                  <div className="truncate font-mono text-[9.5px] text-static/70">
                    {paradigm.variants[0]!.specId}
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-static">
                    {paradigm.affords}
                  </p>
                </button>
              ))}
            </div>
          </>
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
