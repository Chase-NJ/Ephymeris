import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

import { getRig, previewRig, resetRig, saveRig } from "./commands";
import { afterSave, applyPreview, servedView } from "./rigView";
import type { RigAllocation, RigDocument, RigImpact, RigProblem, RigStatus } from "./types";

/**
 * One rig-wiring editing session.
 *
 * The same shape as `useSpecDocument`, because it is the same job: load a
 * document, track dirt, validate continuously, write once. Two differences,
 * both forced by what a wiring document is.
 *
 * VALIDATION IS A ROUND TRIP, not a local check. `hardware.preview` runs the
 * JSON Schema and RIG101–RIG107, RIG109 against the composed channel map — the same rules
 * the compiler runs — so the editor cannot drift from what a save will accept.
 * Debounced at 200 ms, longer than the spec editor's 120 ms because a preview
 * also recompiles every stored task to compute `breaks`.
 *
 * A SAVE CAN BE REFUSED AND STILL BE RIGHT. `confirm: false` comes back as
 * `RIG_WOULD_BREAK_TASKS` when the change would stop a task compiling; that is
 * not a failure to report and retry silently, it is the preflight, and the
 * caller shows it and asks.
 */
export interface RigSession {
  doc: RigDocument | null;
  baseline: RigDocument | null;
  dirty: boolean;
  status: RigStatus | null;
  /** The DRAFT's schema violations and RIG101–RIG107, RIG109. What is wrong with the
   *  rig itself is `status.notices`, which no edit clears (`rigView.ts`). */
  problems: RigProblem[];
  /** Tasks this change would newly stop compiling. */
  breaks: RigImpact[];
  /** The edge codes a save of this draft would issue, as the sidecar plans
   *  them (`TASKS.md#edge-codes`); after a save, the ones it did issue. */
  allocations: RigAllocation[];
  /** The codes the last save issued. Kept through the reload its own
   *  `hardware.updated` triggers, which clears `allocations` (the reloaded
   *  baseline names them); cleared by the next edit. */
  issued: RigAllocation[];
  checking: boolean;
  saving: boolean;
  loadError: string | null;
  actionError: string | null;
  /** The operator confirmed the draft's pins (`status.needsPinConfirmation`). */
  confirmedPins: boolean;
  confirmPins: () => void;
  setDoc: (next: RigDocument) => void;
  revert: () => void;
  /** True when the write landed. False means it was refused — see `breaks`. */
  save: (confirm: boolean) => Promise<boolean>;
  reset: () => Promise<void>;
}

const PREVIEW_DEBOUNCE_MS = 200;

export function useRig(): RigSession {
  const { client, status: link } = useSidecar();
  const connected = link === "connected";

  const [doc, setDocState] = useState<RigDocument | null>(null);
  const [baseline, setBaseline] = useState<RigDocument | null>(null);
  const [status, setStatus] = useState<RigStatus | null>(null);
  /** The served draft's status, which Revert returns to: Save is the
   *  sidecar's answer for a draft, and the baseline is a draft too. */
  const [baselineStatus, setBaselineStatus] = useState<RigStatus | null>(null);
  const [baselineProblems, setBaselineProblems] = useState<RigProblem[]>([]);
  const [confirmedPins, setConfirmedPins] = useState(false);
  const [problems, setProblems] = useState<RigProblem[]>([]);
  const [breaks, setBreaks] = useState<RigImpact[]>([]);
  const [allocations, setAllocations] = useState<RigAllocation[]>([]);
  const [issued, setIssued] = useState<RigAllocation[]>([]);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const load = useCallback(async () => {
    try {
      const reply = await getRig(client);
      setDocState(reply.document as RigDocument);
      setBaseline(reply.document as RigDocument);
      setStatus(reply.status);
      setBaselineStatus(reply.status);
      setConfirmedPins(false);
      setProblems(reply.problems);
      setBaselineProblems(reply.problems);
      setBreaks([]);
      setAllocations([]);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, [client]);

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    void (async () => {
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [connected, load, reload]);

  // Another client saved. The wiring in force is not what this editor loaded,
  // so its `breaks` and `problems` describe a comparison that no longer holds.
  useEffect(
    () => client.on(EVT.HARDWARE_UPDATED, () => setReload((n) => n + 1)),
    [client],
  );

  const dirty = useMemo(
    () => doc !== null && baseline !== null && JSON.stringify(doc) !== JSON.stringify(baseline),
    [doc, baseline],
  );
  useRegisterUnsaved("rig-wiring", dirty);

  /* Debounced preview. `sequence` rather than corr juggling, the same way
   * `useCompile` does it: a reply that is not the newest is dropped, so a fast
   * sequence of drags cannot land an old answer over a new one. */
  const sequence = useRef(0);
  useEffect(() => {
    if (!connected || doc === null) return;
    const served = servedView(
      { dirty, confirmedPins },
      { status: baselineStatus, problems: baselineProblems, breaks: [], allocations: [] },
    );
    if (served !== null) {
      // No preview will describe this draft, so show what the sidecar said
      // about the served one, as Revert does.
      sequence.current += 1;
      setChecking(false);
      setStatus(served.status);
      setProblems(served.problems);
      setBreaks(served.breaks);
      setAllocations(served.allocations);
      return;
    }
    const mine = ++sequence.current;
    setChecking(true);
    const timer = setTimeout(() => {
      void previewRig(client, doc, confirmedPins)
        .then((reply) => {
          if (mine !== sequence.current) return;
          // The draft's problems are replaced; the rig's notices ride on the
          // status, which describes the wiring in force (`rigView.ts`).
          const next = applyPreview({ status, problems, breaks, allocations }, reply);
          setStatus(next.status);
          setProblems(next.problems);
          setBreaks(next.breaks);
          setAllocations(next.allocations);
        })
        .catch((err) => {
          if (mine === sequence.current) setActionError(errorMessage(err));
        })
        .finally(() => {
          if (mine === sequence.current) setChecking(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // `status`, `problems`, `breaks` and `allocations` are what the reply
    // replaces, never what triggers a preview.
  }, [client, connected, doc, dirty, confirmedPins, baselineStatus, baselineProblems]);

  const setDoc = useCallback((next: RigDocument) => {
    setActionError(null);
    setIssued([]);
    setDocState(next);
  }, []);

  const revert = useCallback(() => {
    if (baseline) setDocState(baseline);
    setStatus(baselineStatus);
    setProblems(baselineProblems);
    setConfirmedPins(false);
    setBreaks([]);
    setAllocations([]);
    setIssued([]);
  }, [baseline, baselineStatus, baselineProblems]);

  const save = useCallback(
    async (confirm: boolean) => {
      if (!doc) return false;
      setSaving(true);
      setActionError(null);
      try {
        const reply = await saveRig(client, doc, confirm, confirmedPins);
        const next = afterSave(reply);
        setBaseline(doc);
        setBaselineStatus(next.baseline.status);
        setBaselineProblems(next.baseline.problems);
        setConfirmedPins(next.confirmedPins);
        setStatus(next.view.status);
        setProblems(next.view.problems);
        setBreaks(next.view.breaks);
        setAllocations(next.view.allocations);
        setIssued(next.issued);
        return true;
      } catch (err) {
        // A refusal carries the tasks it would break in `detail`. Surfacing it
        // as a plain error would lose exactly the thing the operator needs.
        const detail = (err as { detail?: { breaks?: RigImpact[] } })?.detail;
        if (detail?.breaks) setBreaks(detail.breaks);
        else setActionError(errorMessage(err));
        return false;
      } finally {
        setSaving(false);
      }
    },
    [client, doc, confirmedPins],
  );

  const confirmPins = useCallback(() => setConfirmedPins(true), []);

  const reset = useCallback(async () => {
    setSaving(true);
    setActionError(null);
    try {
      const reply = await resetRig(client);
      setDocState(reply.document as RigDocument);
      setBaseline(reply.document as RigDocument);
      setStatus(reply.status);
      setBaselineStatus(reply.status);
      setConfirmedPins(false);
      setProblems(reply.problems);
      setBaselineProblems(reply.problems);
      setBreaks([]);
      setAllocations([]);
      setIssued([]);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [client]);

  return {
    doc,
    baseline,
    dirty,
    status,
    problems,
    breaks,
    allocations,
    issued,
    confirmedPins,
    confirmPins,
    checking,
    saving,
    loadError,
    actionError,
    setDoc,
    revert,
    save,
    reset,
  };
}
