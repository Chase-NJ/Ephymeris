import { motion } from "framer-motion";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CircleAlert,
  Download,
  GitCompareArrows,
  Loader2,
  RotateCcw,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { Button, Select } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { DiagnosticsPanel } from "@/components/specs/DiagnosticsPanel";
import { InspectorRail } from "@/components/specs/InspectorRail";
import { ListingDiff } from "@/components/specs/ListingDiff";
import { SpecCanvas } from "@/components/specs/SpecCanvas";
import { SpecForm } from "@/components/specs/SpecForm";
import { SpecInspector } from "@/components/specs/SpecInspector";
import { springPanel } from "@/lib/motion";
import { placeDiagnostics } from "@/lib/specs/diagnostics";
import { topologyOf, toYaml } from "@/lib/specs/document";
import { bandReadouts } from "@/lib/specs/layout";
import { nodesForPath, type Selection } from "@/lib/specs/selection";
import type { SpecDiagnostic, SpecGraph } from "@/lib/specs/types";
import { useCompile } from "@/lib/specs/useCompile";
import { originChip, useSpecDocument } from "@/lib/specs/useSpecDocument";
import { useCapabilities, useSpecs } from "@/lib/specs/useSpecs";
import { useSidecar } from "@/lib/ws/context";

/**
 * Task Designer — one spec, edited through the machine it compiles to.
 *
 * The page is the graph. Everything else is arranged around it: identity and
 * the save/review/export actions above, the fields that produced the current
 * selection to the right, the compiler's diagnostics below. That ordering is
 * the argument the whole screen makes — a task IS its state machine, and the
 * spec is how you say what that machine should be.
 *
 * What the canvas cannot do is as deliberate as what it can. Nodes are not
 * draggable, addable or rewirable, because `topology` is six knobs and a
 * versioned template emits the graph (D1). A free-form node canvas
 * would make invalid machines representable and drag graph validation into the
 * UI — the ordering error the epoch model exists to prevent. So the canvas
 * SELECTS and the inspector EDITS, and the round trip between them is the
 * whole interaction.
 *
 * The other thing kept from the single-page version, because losing it is a
 * data-loss bug rather than a papercut: the document is registered with the
 * sidebar's unsaved guard (inside `useSpecDocument`), so navigating away with
 * an edit in hand asks first.
 */
export function TaskDesigner() {
  const { specId = null } = useParams();
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const { specs, schema, unavailable } = useSpecs();

  const session = useSpecDocument(specId);
  const { doc, baseline, dirty, docId } = session;

  const [view, setView] = useState<"graph" | "parameters">("graph");
  const [selection, setSelection] = useState<Selection>(null);
  const [hoverPath, setHoverPath] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const entry = useMemo(() => specs.find((s) => s.specId === specId) ?? null, [specs, specId]);
  const caps = useCapabilities(useMemo(() => topologyOf(doc), [doc]));
  const { result, compiling, failure } = useCompile(client, connected, doc, specId);
  const placed = useMemo(
    () => (result ? placeDiagnostics(result.diagnostics) : null),
    [result],
  );

  /*
   * THE LAST GRAPH THAT COMPILED.
   *
   * A spec with any ERROR diagnostic produces no table and therefore no graph —
   * the compiler's structural gate, mirrored on the wire. On a page where the
   * graph was a 380px readout, rendering nothing was survivable. Here the graph
   * IS the page, so a mid-edit error would blank the operator's whole frame of
   * reference at exactly the moment they need it to understand the error. Keep
   * the last good picture, dim it, and let the diagnostics say why it is stale.
   */
  const lastGood = useRef<SpecGraph | null>(null);
  if (result?.graph) lastGood.current = result.graph;
  const graph = result?.graph ?? lastGood.current;
  const stale = !result?.graph && lastGood.current !== null;

  const lit = useMemo(
    () => (hoverPath ? nodesForPath(hoverPath, graph, doc ?? {}) : new Set<number>()),
    [hoverPath, graph, doc],
  );

  const readouts = useMemo(() => bandReadouts(topologyOf(doc)), [doc]);

  async function onSave() {
    const target = docId;
    // ONLY NAVIGATE ON A SAVE THAT ACTUALLY LANDED. `save()` swallows its error
    // into `actionError`, so a failed save under a NEW id used to leave the
    // route pointing at a spec that was never written — which then sits on
    // "Opening the spec…" for ever, with the edit still unsaved behind it.
    const saved = await session.save();
    // Saving under a new id created a copy — follow the selection there so
    // "what I'm editing" and "what I just saved" cannot diverge.
    if (saved && target && target !== specId) {
      navigate(`/task/designer/${target}`, { replace: true });
    }
  }

  async function onResetOrDelete() {
    setConfirmReset(false);
    const outcome = await session.resetOrDelete();
    if (outcome === "deleted") navigate("/task");
  }

  if (unavailable) {
    return (
      <Shell>
        <div
          className="surface mx-auto mt-8 max-w-2xl rounded-md px-4 py-3.5 text-[12px] leading-relaxed"
          style={{ color: "var(--color-status-warning)" }}
        >
          {unavailable} Everything else — sketches, sessions, flashing — is unaffected.
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      {/*
        TWO ROWS, NOT ONE WRAPPING ONE. Ten controls on a single `flex-wrap`
        row wrapped into a ragged block at any width below about 1200px, and
        the id — the one thing that must always be readable — was the part
        that moved. Identity and the two actions used constantly stay on top;
        everything occasional goes behind the overflow menu, which has room
        for the labels that were being squeezed.
      */}
      <header className="flex shrink-0 flex-col gap-1 border-b border-halo px-4 py-2">
        <div className="flex items-center gap-x-3">
          <Button variant="ghost" onClick={() => navigate("/task")} title="Back to Task">
            <ArrowLeft size={13} strokeWidth={1.75} />
          </Button>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate font-mono text-[13px] text-starlight">
              {docId ?? specId}
            </span>
            {entry && <OriginChip origin={entry.origin} dirty={dirty} />}
            {docId !== specId && (
              <span className="shrink-0 font-mono text-[9px] text-static">
                → saves as a new spec
              </span>
            )}
          </div>

          <Segmented value={view} onChange={setView} />
          <Button
            variant="primary"
            disabled={!dirty || session.saving || !connected}
            onClick={() => void onSave()}
            title={
              docId !== specId
                ? `Save as a new spec named ${docId}`
                : "Write the edits to this task"
            }
          >
            <Save size={12} strokeWidth={1.75} />
            {session.saving ? "Saving…" : docId !== specId ? `Save as ${docId}` : "Save"}
          </Button>
        </div>

        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <CompileLine compiling={compiling} result={result} />
          </div>
          <ActionsMenu
            disabled={!doc}
            entry={entry}
            exporting={session.exporting}
            onReview={() => setReviewing(true)}
            onExport={(k) => void session.exportArtifact(k)}
            onBench={() => navigate(`/task/bench?spec=${specId ?? ""}`)}
            benchDisabled={!specId}
            onResetOrDelete={() => setConfirmReset(true)}
          />
        </div>
      </header>

      <Notices
        entry={entry}
        dirty={dirty}
        failure={failure}
        actionError={session.actionError}
        openError={session.openError}
        hasDoc={doc !== null}
      />

      {doc && baseline && schema ? (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            {view === "graph" ? (
              graph ? (
                <SpecCanvas
                  graph={graph}
                  placed={placed}
                  selection={selection}
                  onSelect={setSelection}
                  onRevealStructure={(band) => setSelection({ kind: "band", band })}
                  lit={lit}
                  stale={stale}
                  bandReadouts={readouts}
                />
              ) : (
                <p className="m-auto max-w-sm px-6 text-center text-[12px] leading-relaxed text-static">
                  No graph yet — the spec has to compile before there is a machine
                  to draw. The diagnostics below say what is missing.
                </p>
              )
            ) : (
              <div className="scrollbar-none flex-1 overflow-y-auto px-4 py-3">
                <SpecForm
                  doc={doc}
                  baseline={baseline}
                  schema={schema}
                  caps={caps}
                  placed={placed}
                  onChange={session.setDoc}
                />
              </div>
            )}
            {result && (
              <DiagnosticsDrawer
                diagnostics={result.diagnostics}
                onSelectNode={(index) => {
                  setView("graph");
                  setSelection({ kind: "node", index });
                }}
              />
            )}
          </div>

          {view === "graph" && (
            <InspectorRail>
              <SpecInspector
                selection={selection}
                graph={graph}
                doc={doc}
                baseline={baseline}
                schema={schema}
                caps={caps}
                placed={placed}
                onChange={session.setDoc}
                onHoverPath={setHoverPath}
              />
            </InspectorRail>
          )}
        </div>
      ) : (
        <p className="m-auto text-[12px] text-static">
          {session.openError
            ? ""
            : connected
              ? "Opening the spec…"
              : "Waiting for the sidecar…"}
        </p>
      )}

      {specId && doc && (
        <ListingDiff
          open={reviewing}
          onClose={() => setReviewing(false)}
          client={client}
          specId={specId}
          text={toYaml(doc)}
          specs={specs}
        />
      )}

      <Modal
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        title={entry?.origin === "user" ? `Delete ${specId}?` : `Reset ${specId} to shipped?`}
      >
        <p className="text-[13px] leading-relaxed text-static">
          {entry?.origin === "user"
            ? "This deletes the spec. There is no shipped version underneath it, so there is nothing to fall back to."
            : "This discards your copy and restores the spec exactly as it shipped — including its comments, which your edits removed."}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmReset(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void onResetOrDelete()}>
            {entry?.origin === "user" ? "Delete" : "Reset to shipped"}
          </Button>
        </div>
      </Modal>
    </Shell>
  );
}

/**
 * The route's frame.
 *
 * `SkyBackdrop` at zero opacity rather than omitted: a route that mounts no
 * constellation is the only thing that triggers a real stage release, which
 * destroys three's refcounted shader programs and lands a ~300 ms stall in the
 * next frame's delta. This page wants a plain background and still has to hold
 * the canvas open for the rest of the app (`SkyBackdrop`'s own caution block).
 */
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

/** One line per band, from the knobs — what the four band cards used to say. */

function CompileLine({
  compiling,
  result,
}: {
  compiling: boolean;
  result: ReturnType<typeof useCompile>["result"];
}) {
  if (compiling) {
    return (
      <span className="flex items-center gap-1.5 font-mono text-[10px] text-static">
        <Loader2 size={10} strokeWidth={1.75} className="animate-spin" />
        compiling…
      </span>
    );
  }
  if (result?.ok && result.table) {
    const t = result.table;
    return (
      <span className="flex items-center gap-1.5 font-mono text-[10px] text-static">
        <Check size={10} strokeWidth={2} style={{ color: "var(--color-status-ok)" }} />
        {t.nNodes} states · {t.nEdges} edges · {t.nTrialTypes} trial type
        {t.nTrialTypes === 1 ? "" : "s"} · {t.sizeBytes} bytes · {t.specHash}
      </span>
    );
  }
  if (result) {
    const errors = result.diagnostics.filter((d) => d.severity === "ERROR").length;
    return (
      <span className="flex items-center gap-1.5 font-mono text-[10px] text-static">
        <CircleAlert
          size={10}
          strokeWidth={1.75}
          style={{ color: "var(--color-status-error)" }}
        />
        {errors} error{errors === 1 ? "" : "s"} — no table until they&rsquo;re fixed
      </span>
    );
  }
  return null;
}

function Notices({
  entry,
  dirty,
  failure,
  actionError,
  openError,
  hasDoc,
}: {
  entry: { origin: string } | null;
  dirty: boolean;
  failure: string | null;
  actionError: string | null;
  openError: string | null;
  hasDoc: boolean;
}) {
  const anything =
    (entry?.origin === "shipped" && dirty) ||
    failure ||
    actionError ||
    (openError && !hasDoc);
  if (!anything) return null;

  return (
    <div className="flex shrink-0 flex-col gap-1.5 border-b border-halo px-4 py-2">
      {/* The one-time honesty note: saving rewrites the file through the form's
      serializer, and the shipped specs' comments cite firmware line numbers —
      real documentation. Shown while the FIRST divergence from a pure shipped
      spec is on screen, which is exactly when the choice is being made. */}
      {entry?.origin === "shipped" && dirty && (
        <p className="text-[11px] leading-relaxed text-static">
          Saving makes this rig&rsquo;s own copy and rewrites the file — the shipped
          version&rsquo;s comments stay recoverable via{" "}
          <span className="text-starlight">Reset to shipped</span>.
        </p>
      )}
      {(failure || actionError || (openError && !hasDoc)) && (
        <p className="text-[11px]" style={{ color: "var(--color-status-error)" }}>
          {failure ?? actionError ?? openError}
        </p>
      )}
    </div>
  );
}

/**
 * Diagnostics as a drawer rather than a panel at the end of a scroll.
 *
 * Collapsed it is one line with the counts, which is the state it spends most
 * of its life in; open it lists everything, and clicking a node-anchored one
 * selects that node on the canvas. It never filters — a diagnostic that reaches
 * nobody is the failure mode this whole path is built to avoid.
 */
function DiagnosticsDrawer({
  diagnostics,
  onSelectNode,
}: {
  diagnostics: SpecDiagnostic[];
  onSelectNode: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const errors = diagnostics.filter((d) => d.severity === "ERROR").length;
  const warnings = diagnostics.filter((d) => d.severity === "WARN").length;

  return (
    <div className="shrink-0 border-t border-halo">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-1.5 font-mono text-[10px] text-static transition-colors hover:text-starlight"
      >
        <span className="tracking-wider uppercase">Diagnostics</span>
        {errors > 0 && (
          <span style={{ color: "var(--color-status-error)" }}>{errors} error</span>
        )}
        {warnings > 0 && (
          <span style={{ color: "var(--color-status-warning)" }}>{warnings} warn</span>
        )}
        {errors === 0 && warnings === 0 && <span>clean</span>}
        <span className="ml-auto">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="scrollbar-none max-h-[26vh] overflow-y-auto px-4 pb-3">
          <DiagnosticsPanel diagnostics={diagnostics} onSelectNode={onSelectNode} />
        </div>
      )}
    </div>
  );
}

function Segmented({
  value,
  onChange,
}: {
  value: "graph" | "parameters";
  onChange: (next: "graph" | "parameters") => void;
}) {
  return (
    <span className="flex overflow-hidden rounded-sm border border-halo">
      {(["graph", "parameters"] as const).map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          className={`px-2.5 py-1 text-[11px] capitalize transition-colors ${
            value === key
              ? "bg-halo/70 text-starlight"
              : "text-static hover:text-starlight"
          }`}
        >
          {key}
        </button>
      ))}
    </span>
  );
}

/**
 * Review, Export, Bench and Reset behind one control.
 *
 * All four are occasional — you review before saving, you go to the bench once
 * a table is worth putting on a box, you reset almost never — and on the header
 * row they were competing for width with the id and the compile line, which are
 * read constantly. In here the export picker gets its full label text back
 * ("wire bytes (.bin)" was being clipped at 152px) and nothing wraps.
 */
function ActionsMenu({
  disabled,
  entry,
  exporting,
  onReview,
  onExport,
  onBench,
  benchDisabled,
  onResetOrDelete,
}: {
  disabled: boolean;
  entry: { origin: string } | null;
  exporting: boolean;
  onReview: () => void;
  onExport: (kind: string) => void;
  onBench: () => void;
  benchDisabled: boolean;
  onResetOrDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("listing");

  return (
    <span className="relative flex shrink-0 items-center">
      <Button variant="ghost" onClick={() => setOpen((v) => !v)} title="More actions">
        Actions
        <ChevronDown size={12} strokeWidth={1.75} />
      </Button>

      {open && (
        <>
          {/* Click-away, so the menu is not a mode with no exit. */}
          <span className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <span className="surface absolute top-full right-0 z-50 mt-1 flex w-[268px] flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
            <Button
              variant="ghost"
              disabled={disabled}
              onClick={() => {
                setOpen(false);
                onReview();
              }}
              title="Diff the compiled listing against a baseline — the review artifact"
            >
              <GitCompareArrows size={12} strokeWidth={1.75} />
              Review changes
            </Button>

            <span className="flex items-center gap-1 border-t border-halo pt-1.5">
              <Select
                label="Export artifact"
                value={kind}
                options={[
                  { value: "listing", label: "listing (.table.txt)" },
                  { value: "spec", label: "spec (.yaml)" },
                  { value: "table_json", label: "table (.json)" },
                  { value: "table_bin", label: "wire bytes (.bin)" },
                  { value: "bench", label: "bench card (.txt)" },
                  { value: "lint", label: "lint baseline (.txt)" },
                ]}
                onChange={(v) => setKind(String(v))}
                className="min-w-0 flex-1"
              />
              <Button
                variant="ghost"
                disabled={disabled || exporting}
                onClick={() => onExport(kind)}
                title="Export"
              >
                <Download size={12} strokeWidth={1.75} />
              </Button>
            </span>

            <Button
              variant="ghost"
              disabled={benchDisabled}
              onClick={() => {
                setOpen(false);
                onBench();
              }}
              title="Put this table on a bench box — not for animal use"
            >
              <Upload size={12} strokeWidth={1.75} />
              Bench
            </Button>

            {entry && entry.origin !== "shipped" && (
              <Button
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                  onResetOrDelete();
                }}
                title={
                  entry.origin === "user"
                    ? "Delete this spec"
                    : "Discard your copy and restore the shipped spec — comments and all"
                }
              >
                {entry.origin === "user" ? (
                  <Trash2 size={12} strokeWidth={1.75} />
                ) : (
                  <RotateCcw size={12} strokeWidth={1.75} />
                )}
                {entry.origin === "user" ? "Delete" : "Reset to shipped"}
              </Button>
            )}
          </span>
        </>
      )}
    </span>
  );
}

function OriginChip({ origin, dirty }: { origin: string; dirty: boolean }) {
  const { label, color } = originChip(origin as never, dirty);
  return (
    <span
      className="rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[9px] tracking-wider"
      style={{ color }}
    >
      {label}
    </span>
  );
}
