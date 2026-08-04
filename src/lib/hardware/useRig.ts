import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

import { getRig, previewRig, resetRig, saveRig } from "./commands";
import type { RigDocument, RigImpact, RigProblem, RigStatus } from "./types";

/**
 * One rig-wiring editing session.
 *
 * The same shape as `useSpecDocument`, because it is the same job: load a
 * document, track dirt, validate continuously, write once. Two differences,
 * both forced by what a wiring document is.
 *
 * VALIDATION IS A ROUND TRIP, not a local check. `hardware.preview` runs the
 * JSON Schema and TG226-229 against the composed channel map — the same rules
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
  /** Schema violations and TG226-229, for the document as it stands. */
  problems: RigProblem[];
  /** Tasks this change would newly stop compiling. */
  breaks: RigImpact[];
  checking: boolean;
  saving: boolean;
  loadError: string | null;
  actionError: string | null;
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
  const [problems, setProblems] = useState<RigProblem[]>([]);
  const [breaks, setBreaks] = useState<RigImpact[]>([]);
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
      setProblems(reply.problems);
      setBreaks([]);
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
    if (!connected || doc === null || !dirty) return;
    const mine = ++sequence.current;
    setChecking(true);
    const timer = setTimeout(() => {
      void previewRig(client, doc)
        .then((reply) => {
          if (mine !== sequence.current) return;
          setProblems(reply.problems);
          setBreaks(reply.breaks);
        })
        .catch((err) => {
          if (mine === sequence.current) setActionError(errorMessage(err));
        })
        .finally(() => {
          if (mine === sequence.current) setChecking(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [client, connected, doc, dirty]);

  const setDoc = useCallback((next: RigDocument) => {
    setActionError(null);
    setDocState(next);
  }, []);

  const revert = useCallback(() => {
    if (baseline) setDocState(baseline);
    setBreaks([]);
  }, [baseline]);

  const save = useCallback(
    async (confirm: boolean) => {
      if (!doc) return false;
      setSaving(true);
      setActionError(null);
      try {
        const reply = await saveRig(client, doc, confirm);
        setBaseline(doc);
        setStatus(reply.status);
        setProblems(reply.problems);
        setBreaks(reply.breaks);
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
    [client, doc],
  );

  const reset = useCallback(async () => {
    setSaving(true);
    setActionError(null);
    try {
      const reply = await resetRig(client);
      setDocState(reply.document as RigDocument);
      setBaseline(reply.document as RigDocument);
      setStatus(reply.status);
      setProblems(reply.problems);
      setBreaks([]);
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
