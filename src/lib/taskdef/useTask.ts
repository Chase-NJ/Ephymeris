import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";
import type { TaskProfile } from "@/lib/ws/protocol";

import { getTask, previewTask, saveTask } from "./commands";
import type { TaskDefinition, TaskDiagnostic } from "./types";

/**
 * One task-profile editing session.
 *
 * The same shape as `useRig`, because it is the same job: load a document,
 * track dirt, validate continuously, write once. Three things are specific to
 * a task.
 *
 * VALIDATION IS A ROUND TRIP. `tasks.preview` runs the eleven rules against the
 * COMPOSED channel map — the same code the save will run — so the editor cannot
 * drift from what a save accepts. Most of those rules depend on the wiring, and
 * the frontend has no copy of it.
 *
 * THE PREVIEW ALSO CARRIES THE COMPILED PROFILE, which is what the state
 * machine and the parameter rail draw. So one round trip per edit redraws the
 * whole page, and the diagram an operator is looking at is always the one their
 * current document produces rather than the last saved one.
 *
 * AND THE `START` LINE LENGTH. That is the one budget an operator can exhaust
 * without noticing: the firmware truncates an overlong line in silence and runs
 * on whichever values happened to fit. Showing the number as the ramp grows is
 * cheaper than explaining the failure afterward.
 */
export interface TaskSession {
  definition: TaskDefinition | null;
  baseline: TaskDefinition | null;
  dirty: boolean;
  /** What the definition compiles to — the state machine and the rail read it. */
  profile: TaskProfile | null;
  /** `metadataKey` → the value with NO override. What the rail measures
   *  divergence against, and what a per-field reset falls back to. */
  catalogueDefaults: Record<string, unknown>;
  diagnostics: TaskDiagnostic[];
  startLine: { length: number; max: number } | null;
  checking: boolean;
  saving: boolean;
  loadError: string | null;
  actionError: string | null;
  setDefinition: (next: TaskDefinition) => void;
  revert: () => void;
  save: () => Promise<boolean>;
}

/** Longer than the wiring editor's 200 ms: a preview generates four files. */
const PREVIEW_DEBOUNCE_MS = 250;

export function useTask(
  taskId: string | null,
  /** A definition to open unsaved — a duplicate of an existing task. */
  seed?: TaskDefinition | null,
): TaskSession {
  const { client, status: link } = useSidecar();
  const connected = link === "connected";

  const [definition, setState] = useState<TaskDefinition | null>(null);
  const [baseline, setBaseline] = useState<TaskDefinition | null>(null);
  const [profile, setProfile] = useState<TaskProfile | null>(null);
  const [catalogueDefaults, setCatalogue] = useState<Record<string, unknown>>({});
  const [diagnostics, setDiagnostics] = useState<TaskDiagnostic[]>([]);
  const [startLine, setStartLine] = useState<{ length: number; max: number } | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!connected) return;
    // A seeded definition is UNSAVED by construction (nothing has written it
    // yet), so its baseline is null: everything about it is dirty, and
    // "revert" has nothing to go back to.
    if (seed) {
      setState(seed);
      setBaseline(null);
      setLoadError(null);
      return;
    }
    if (!taskId) {
      setState(null);
      setBaseline(null);
      return;
    }
    let cancelled = false;
    void getTask(client, taskId)
      .then((reply) => {
        if (cancelled) return;
        const doc = reply.definition as TaskDefinition;
        setState(doc);
        setBaseline(doc);
        setDiagnostics(reply.diagnostics);
        setLoadError(null);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(errorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client, connected, taskId, seed]);

  const dirty = useMemo(
    () =>
      definition !== null &&
      (baseline === null || JSON.stringify(definition) !== JSON.stringify(baseline)),
    [definition, baseline],
  );
  useRegisterUnsaved("task-profile", dirty);

  /* Debounced preview, keyed by a sequence rather than by corr: a reply that is
   * not the newest is dropped, so a fast sequence of edits cannot land an old
   * diagram over a new one. It runs even when NOT dirty, because a freshly
   * loaded definition still needs its profile to draw.
   *
   * THE FIRST PREVIEW OF A FRESHLY OPENED DEFINITION SKIPS THE DEBOUNCE. The
   * wait exists to coalesce keystrokes; on open there are no keystrokes to
   * coalesce, and it only held the diagram and the parameter rail back a
   * quarter second after the rest of the page — which is what made the Task
   * tab land in two visible pops. Reference equality is the load signal: a
   * load sets `definition === baseline` (a seeded open, `=== seed`), and any
   * edit produces a new object. */
  const sequence = useRef(0);
  useEffect(() => {
    if (!connected || definition === null) return;
    const immediate = definition === baseline || definition === seed;
    const mine = ++sequence.current;
    setChecking(true);
    const timer = setTimeout(() => {
      void previewTask(client, definition)
        .then((reply) => {
          if (mine !== sequence.current) return;
          setDiagnostics(reply.diagnostics);
          setProfile(reply.profile);
          setCatalogue(reply.catalogueDefaults as Record<string, unknown>);
          setStartLine({ length: reply.startLineLength, max: reply.startLineMax });
        })
        .catch((err) => {
          if (mine === sequence.current) setActionError(errorMessage(err));
        })
        .finally(() => {
          if (mine === sequence.current) setChecking(false);
        });
    }, immediate ? 0 : PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // `baseline`/`seed` are read for the debounce choice only, and both are set
    // in the same commit as `definition` on a load — the closure is never
    // stale. Depending on them would refire a full preview after every save
    // (the save moves `baseline` to the definition by reference).
  }, [client, connected, definition]);

  /* Another client rewired the rig. Every diagnostic here was computed against
   * the old wiring, so they describe a comparison that no longer holds — and a
   * task can be broken by a rewiring it never saw. */
  useEffect(
    () => client.on(EVT.HARDWARE_UPDATED, () => setState((d) => (d ? { ...d } : d))),
    [client],
  );

  const setDefinition = useCallback((next: TaskDefinition) => {
    setActionError(null);
    setState(next);
  }, []);

  const revert = useCallback(() => {
    if (baseline) setState(baseline);
  }, [baseline]);

  const save = useCallback(async () => {
    if (!definition) return false;
    setSaving(true);
    setActionError(null);
    try {
      const reply = await saveTask(client, definition);
      // The save ALWAYS lands, diagnostics or not — a half-finished task must
      // be savable, and the gate is flashing. So the baseline moves either way.
      setBaseline(definition);
      setDiagnostics(reply.diagnostics);
      return true;
    } catch (err) {
      setActionError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }, [client, definition]);

  return {
    definition,
    baseline,
    dirty,
    profile,
    catalogueDefaults,
    diagnostics,
    startLine,
    checking,
    saving,
    loadError,
    actionError,
    setDefinition,
    revert,
    save,
  };
}
