import { Check, CircleAlert, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Select } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { getSpec } from "@/lib/specs/commands";
import { placeDiagnostics } from "@/lib/specs/diagnostics";
import type { SpecDocument } from "@/lib/specs/types";
import { useCompile } from "@/lib/specs/useCompile";
import { useCapabilities, useSpecs } from "@/lib/specs/useSpecs";
import { useSidecar } from "@/lib/ws/context";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { SpecForm } from "./SpecForm";

/**
 * The task-spec workbench — the Task screen's spec-first half.
 *
 * Read-only phase: the form edits an in-memory document and the compiler
 * checks every edit live, but nothing writes to disk yet. That is still most
 * of the day-to-day value — an operator can open a shipped task, tune a
 * timing, and watch the compiler agree or object within ~150 ms — and it is
 * exactly the loop a save button will later commit.
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
            <div className="text-[13px] font-medium text-starlight">Task spec</div>
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
                label: s.label ? `${s.specId} — ${s.label}` : s.specId,
              })),
            ]}
            onChange={(v) => setSpecId(v === "" ? null : String(v))}
            disabled={!connected || loading}
            className="w-[260px] shrink-0 truncate"
          />
        </div>

        {specId && (
          <div className="mt-2 flex items-center gap-2 font-mono text-[10px] text-static">
            {compiling ? (
              <>
                <Loader2 size={11} strokeWidth={1.75} className="animate-spin" />
                compiling…
              </>
            ) : result?.ok && result.table ? (
              <>
                <Check size={11} strokeWidth={2} style={{ color: "var(--color-status-ok)" }} />
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
                {result.diagnostics.filter((d) => d.severity === "ERROR").length} error(s) —
                no table is produced until they're fixed
              </>
            ) : null}
          </div>
        )}

        {failure && (
          <p className="mt-2 text-[11px]" style={{ color: "var(--color-status-error)" }}>
            {failure}
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
          <SpecForm
            doc={doc}
            baseline={baseline}
            schema={schema}
            caps={caps}
            placed={placed}
            onChange={setDoc}
          />
          {result && <DiagnosticsPanel diagnostics={result.diagnostics} />}
        </div>
      )}
    </section>
  );
}
