import {
  Check,
  CircleAlert,
  Download,
  GitCompareArrows,
  Loader2,
  RotateCcw,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import {
  acknowledgeUpstream,
  deleteSpec,
  exportSpec,
  getSpec,
  saveSpec,
} from "@/lib/specs/commands";
import { placeDiagnostics } from "@/lib/specs/diagnostics";
import { toYaml } from "@/lib/specs/document";
import type { SpecDocument } from "@/lib/specs/types";
import { useCompile } from "@/lib/specs/useCompile";
import { useCapabilities, useSpecs } from "@/lib/specs/useSpecs";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";
import { BandPalette } from "./BandPalette";
import { BoardBench } from "./BoardBench";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { ListingDiff } from "./ListingDiff";
import { SpecForm } from "./SpecForm";
import { SpecGraph } from "./SpecGraph";

/**
 * The task-spec workbench — the Task screen's spec-first half.
 *
 * The form edits an in-memory document; the compiler checks every edit live;
 * Save writes the user's copy under the sidecar's app-data dir. A save over a
 * shipped spec's id SHADOWS it — the shipped file is never modified, which is
 * what makes Reset to shipped a byte-for-byte restore, comments included.
 *
 * The save target is THE DOCUMENT'S OWN spec_id, not the picker's selection:
 * editing the id field and saving therefore creates a copy (origin `user`)
 * and leaves the original alone — the whole create/duplicate flow rides one
 * text field instead of a modal. The sidecar refuses a parsed document whose
 * id disagrees with the target, so the two cannot drift.
 *
 * A spec is a SIBLING artifact to a sketch's task.json (the legacy section
 * below this one), never an extension of it. See docs/tasks.md §4.1 for the
 * hash-splitting reason that boundary must hold.
 */
export function SpecWorkbench() {
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const { specs, schema, unavailable, loading } = useSpecs();

  const [specId, setSpecId] = useState<string | null>(null);
  const [doc, setDoc] = useState<SpecDocument | null>(null);
  const [baseline, setBaseline] = useState<SpecDocument | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!specId) {
      setDoc(null);
      setBaseline(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const reply = await getSpec(client, specId);
        if (cancelled) return;
        setDoc(reply.raw);
        setBaseline(reply.raw);
        setSaveError(null);
        setOpenError(
          reply.raw === null
            ? "This spec's YAML won't parse, so the form can't open it."
            : null,
        );
      } catch (err) {
        if (!cancelled) setOpenError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, specId]);

  const entry = useMemo(
    () => specs.find((s) => s.specId === specId) ?? null,
    [specs, specId],
  );

  const dirty = useMemo(
    () =>
      doc !== null &&
      baseline !== null &&
      JSON.stringify(doc) !== JSON.stringify(baseline),
    [doc, baseline],
  );
  // The sidebar's discard-guard — a mis-click must not silently drop an edit.
  useRegisterUnsaved("spec-editor", dirty);

  const topology = useMemo(() => {
    const t = doc?.["topology"];
    return t !== null && typeof t === "object" ? (t as Record<string, unknown>) : null;
  }, [doc]);

  const caps = useCapabilities(topology);
  const { result, compiling, failure } = useCompile(client, connected, doc, specId);
  const placed = useMemo(
    () => (result ? placeDiagnostics(result.diagnostics) : null),
    [result],
  );

  /** The id the document declares — the save target. */
  const docId = useMemo(() => {
    const declared = doc?.["spec_id"];
    return typeof declared === "string" && declared.trim() !== "" ? declared : specId;
  }, [doc, specId]);

  async function save() {
    if (!doc || !docId) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveSpec(client, docId, toYaml(doc));
      setBaseline(doc);
      // Saving under a new id created a copy — follow the selection there so
      // "what I'm editing" and "what I just saved" cannot diverge.
      if (docId !== specId) setSpecId(docId);
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function resetToShipped() {
    if (!specId) return;
    setConfirmReset(false);
    setSaveError(null);
    try {
      const reply = await deleteSpec(client, specId);
      if (reply.entry === null) {
        // A user spec is simply gone.
        setSpecId(null);
      } else {
        const restored = await getSpec(client, specId);
        setDoc(restored.raw);
        setBaseline(restored.raw);
      }
    } catch (err) {
      setSaveError(errorMessage(err));
    }
  }

  async function keepMine() {
    if (!specId) return;
    setSaveError(null);
    try {
      await acknowledgeUpstream(client, specId);
    } catch (err) {
      setSaveError(errorMessage(err));
    }
  }

  /**
   * Export one artifact: bytes come back in the reply and are written through
   * the user's own save dialog — the sidecar never writes outside its data
   * dir, and the dialog is what scopes the write (`capture.ts`'s pattern).
   */
  async function exportArtifact(kind: string) {
    if (!doc || !specId) return;
    setExporting(true);
    setSaveError(null);
    try {
      const reply = await exportSpec(client, specId, toYaml(doc), [kind]);
      const artifact = reply.artifacts[0];
      if (!artifact) {
        setSaveError(
          "Nothing to export — every artifact except the YAML needs a spec that compiles.",
        );
        return;
      }
      const { save } = await import("@tauri-apps/plugin-dialog");
      const path = await save({ defaultPath: artifact.filename });
      if (!path) return; // cancel is an outcome, not an error
      if (artifact.base64 !== null) {
        const { writeFile } = await import("@tauri-apps/plugin-fs");
        await writeFile(
          path,
          Uint8Array.from(atob(artifact.base64), (c) => c.charCodeAt(0)),
        );
      } else {
        const { writeTextFile } = await import("@tauri-apps/plugin-fs");
        await writeTextFile(path, artifact.text ?? "");
      }
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  if (unavailable) {
    return (
      <section className="surface mt-6 rounded-md px-4 py-3.5">
        <div
          className="flex items-start gap-2 text-[12px] leading-relaxed"
          style={{ color: "var(--color-status-warning)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          <span>
            {unavailable} Everything else — sketches, sessions, flashing — is
            unaffected.
          </span>
        </div>
      </section>
    );
  }

  return (
    <section className="surface mt-6 rounded-md">
      <div className="border-b border-halo px-4 py-3.5">
        <div className="flex items-start justify-between gap-8">
          <div className="min-w-0 pt-0.5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium text-starlight">Task spec</span>
              {entry && <OriginChip origin={entry.origin} dirty={dirty} />}
            </div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-static">
              A compiled task: the spec is data, the board runs a fixed
              interpreter, and every edit below is checked by the same compiler
              that builds the table a box would receive.
            </p>
          </div>
          <Select
            label="Task spec"
            value={specId ?? ""}
            options={[
              { value: "", label: loading ? "loading…" : "— select a spec —" },
              ...specs.map((s) => ({
                value: s.specId,
                label:
                  (s.label ? `${s.specId} — ${s.label}` : s.specId) +
                  (s.origin === "shipped_edited" ? " •" : s.origin === "user" ? " ◦" : "") +
                  (s.upstreamChanged ? " ⚠" : ""),
              })),
            ]}
            onChange={(v) => setSpecId(v === "" ? null : String(v))}
            disabled={!connected || loading}
            className="w-[260px] shrink-0 truncate"
          />
        </div>

        {specId && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 font-mono text-[10px] text-static">
              {compiling ? (
                <>
                  <Loader2 size={11} strokeWidth={1.75} className="animate-spin" />
                  compiling…
                </>
              ) : result?.ok && result.table ? (
                <>
                  <Check
                    size={11}
                    strokeWidth={2}
                    style={{ color: "var(--color-status-ok)" }}
                  />
                  {result.table.nNodes} states · {result.table.nEdges} edges ·{" "}
                  {result.table.nTiming} timing · {result.table.sizeBytes} bytes ·{" "}
                  {result.table.specHash}
                </>
              ) : result ? (
                <>
                  <CircleAlert
                    size={11}
                    strokeWidth={1.75}
                    style={{ color: "var(--color-status-error)" }}
                  />
                  {result.diagnostics.filter((d) => d.severity === "ERROR").length}{" "}
                  error(s) — no table is produced until they're fixed
                </>
              ) : null}
            </div>

            <div className="flex items-center gap-1.5">
              <Button
                variant="ghost"
                disabled={!doc}
                onClick={() => setReviewing(true)}
                title="Diff the compiled listing against a baseline — the review artifact"
              >
                <GitCompareArrows size={12} strokeWidth={1.75} />
                Review
              </Button>
              <ExportMenu disabled={!doc || exporting} onExport={(k) => void exportArtifact(k)} />
              {entry?.origin === "shipped_edited" && (
                <Button
                  variant="ghost"
                  onClick={() => setConfirmReset(true)}
                  title="Discard your copy and restore the shipped spec — comments and all"
                >
                  <RotateCcw size={12} strokeWidth={1.75} />
                  Reset to shipped
                </Button>
              )}
              {entry?.origin === "user" && (
                <Button
                  variant="ghost"
                  onClick={() => setConfirmReset(true)}
                  title="Delete this spec"
                >
                  <Trash2 size={12} strokeWidth={1.75} />
                  Delete
                </Button>
              )}
              <Button
                variant="primary"
                disabled={!dirty || saving || !connected}
                onClick={() => void save()}
                title={
                  docId !== specId
                    ? `Save as a new spec named ${docId}`
                    : "Save this rig's copy"
                }
              >
                <Save size={12} strokeWidth={1.75} />
                {saving ? "Saving…" : docId !== specId ? `Save as ${docId}` : "Save"}
              </Button>
            </div>
          </div>
        )}

        {/* The one-time honesty note: saving rewrites the file through the
        form's serializer, and the shipped specs' comments cite firmware line
        numbers — real documentation. Shown while the FIRST divergence from a
        pure shipped spec is on screen, which is exactly the moment the choice
        is being made. */}
        {entry?.origin === "shipped" && dirty && (
          <p className="mt-2 text-[11px] leading-relaxed text-static">
            Saving makes this rig's own copy and rewrites the file — the shipped
            version's comments stay recoverable via{" "}
            <span className="text-starlight">Reset to shipped</span>.
          </p>
        )}

        {entry?.upstreamChanged && (
          <div
            className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-sm border border-halo px-2.5 py-2 text-[11px]"
            style={{ color: "var(--color-status-warning)" }}
          >
            <span>
              An app update changed the shipped version of this spec underneath
              your edits. Nothing was merged.
            </span>
            <span className="flex gap-1.5">
              <Button variant="ghost" onClick={() => void keepMine()}>
                Keep mine
              </Button>
              <Button variant="ghost" onClick={() => setConfirmReset(true)}>
                Take the new shipped version
              </Button>
            </span>
          </div>
        )}

        {(failure || saveError) && (
          <p className="mt-2 text-[11px]" style={{ color: "var(--color-status-error)" }}>
            {failure ?? saveError}
          </p>
        )}
        {openError && !doc && (
          <p className="mt-2 text-[11px]" style={{ color: "var(--color-status-error)" }}>
            {openError}
          </p>
        )}
      </div>

      {doc && baseline && schema && (
        <div className="flex flex-col gap-5 px-4 py-3.5">
          <BandPalette
            doc={doc}
            baseline={baseline}
            schema={schema}
            caps={caps}
            graph={result?.graph ?? null}
            placed={placed}
            onChange={setDoc}
          />
          {result?.graph && <SpecGraph graph={result.graph} placed={placed} />}
          <SpecForm
            doc={doc}
            baseline={baseline}
            schema={schema}
            caps={caps}
            placed={placed}
            onChange={setDoc}
          />
          {result && <DiagnosticsPanel diagnostics={result.diagnostics} />}
          {specId && (
            <BoardBench
              specId={specId}
              doc={doc}
              compiled={result?.ok === true && result.table !== null}
            />
          )}
        </div>
      )}

      {specId && doc && (
        <ListingDiff
          open={reviewing}
          onClose={() => setReviewing(false)}
          client={client}
          specId={specId}
          text={toYaml(doc)}
          specs={specs}
          hasShipped={entry?.origin !== "user"}
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
          <Button variant="primary" onClick={() => void resetToShipped()}>
            {entry?.origin === "user" ? "Delete" : "Reset to shipped"}
          </Button>
        </div>
      </Modal>
    </section>
  );
}

/** One artifact per export — the picker doubles as the explanation of what
 * each artifact is, and the save dialog scopes the write. */
function ExportMenu({
  disabled,
  onExport,
}: {
  disabled: boolean;
  onExport: (kind: string) => void;
}) {
  const [kind, setKind] = useState("listing");
  return (
    <span className="flex items-center gap-1">
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
        className="w-[168px]"
      />
      <Button variant="ghost" disabled={disabled} onClick={() => onExport(kind)} title="Export">
        <Download size={12} strokeWidth={1.75} />
      </Button>
    </span>
  );
}

function OriginChip({ origin, dirty }: { origin: string; dirty: boolean }) {
  const [label, color] =
    origin === "user"
      ? ["YOURS", "var(--color-ion)"]
      : origin === "shipped_edited" || dirty
        ? ["EDITED", "var(--color-pulsar)"]
        : ["SHIPPED", "var(--color-static)"];
  return (
    <span
      className="rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[9px] tracking-wider"
      style={{ color }}
    >
      {label}
    </span>
  );
}
