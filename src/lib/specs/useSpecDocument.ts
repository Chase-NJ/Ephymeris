import { useCallback, useEffect, useMemo, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useRegisterUnsaved } from "@/lib/nav/unsavedGuard";
import { useSidecar } from "@/lib/ws/context";
import {
  deleteSpec,
  exportSpec,
  getSpec,
  saveSpec,
} from "./commands";
import { toYaml } from "./document";
import type { SpecDocument, SpecOrigin } from "./types";

/**
 * One spec's editing session: load, dirty-tracking, save, reset, export.
 *
 * Lifted out of the old single-page workbench so the Designer's header, canvas
 * and inspector are three views of one state rather than three props threaded
 * through a 500-line component. Every rule it carries was already load-bearing:
 *
 * THE SAVE TARGET IS THE DOCUMENT'S OWN `spec_id`, not the route's. Editing the
 * id field and saving therefore creates a copy and leaves the original alone —
 * which is the entire duplicate flow, riding one text field. The sidecar
 * refuses a parsed document whose id disagrees with the target, so the two
 * cannot drift.
 *
 * A save over a bundled spec's id SHADOWS it. The shipped file is never
 * modified, which is what makes Reset a byte-for-byte restore, comments and
 * all — and the store baselines the shipped bytes *before* the user file
 * exists, so no ordering leaves an edit without its undo.
 */
export interface SpecSession {
  doc: SpecDocument | null;
  baseline: SpecDocument | null;
  dirty: boolean;
  /** The id the document declares — the save target, which may be a new one. */
  docId: string | null;
  saving: boolean;
  /** Why the form couldn't open this spec (unparseable YAML, or a load error). */
  openError: string | null;
  /** Why the last save/reset/export failed. */
  actionError: string | null;
  setDoc: (next: SpecDocument) => void;
  /** True when the save landed. A caller that routes on it must check —
   * the failure is reported through `actionError`, not thrown. */
  save: () => Promise<boolean>;
  /** Delete a user spec, or restore a shadowed one to its shipped bytes. */
  resetOrDelete: () => Promise<"deleted" | "restored" | null>;
  /** "Keep mine" — re-baseline against the new shipped bytes, merging nothing. */
  exportArtifact: (kind: string) => Promise<void>;
  exporting: boolean;
}

export function useSpecDocument(specId: string | null): SpecSession {
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [doc, setDoc] = useState<SpecDocument | null>(null);
  const [baseline, setBaseline] = useState<SpecDocument | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  /* Reset keeps the same specId, so the load effect below cannot see it. This
   * counter is what re-runs the load for an action that changed the file
   * underneath an unchanged selection. */
  const [reload, setReload] = useState(0);

  /*
   * Waiting for `connected` is load-bearing on a route, in a way it was not on
   * the old single page. There the spec was chosen from a picker, which could
   * not be touched before the socket was up; here the id comes from the URL, so
   * a reload or a deep link mounts this hook while the client is still
   * reconnecting. Firing then failed once, permanently, on a page whose whole
   * content depends on the reply.
   */
  useEffect(() => {
    if (!specId || !connected) {
      if (!specId) {
        setDoc(null);
        setBaseline(null);
      }
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const reply = await getSpec(client, specId);
        if (cancelled) return;
        setDoc(reply.raw);
        setBaseline(reply.raw);
        setActionError(null);
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
  }, [client, connected, specId, reload]);

  const dirty = useMemo(
    () =>
      doc !== null && baseline !== null && JSON.stringify(doc) !== JSON.stringify(baseline),
    [doc, baseline],
  );

  // The sidebar's discard guard — a mis-click must not silently drop an edit.
  useRegisterUnsaved("spec-editor", dirty);

  const docId = useMemo(() => {
    const declared = doc?.["spec_id"];
    return typeof declared === "string" && declared.trim() !== "" ? declared : specId;
  }, [doc, specId]);

  /**
   * Returns whether the save actually landed.
   *
   * The error is still surfaced through `actionError` — that has not changed —
   * but a caller that ROUTES on a save needs to know, and `void` forced it to
   * assume success. Saving under a new id and then navigating to a spec the
   * sidecar refused left the route on a document that does not exist.
   */
  const save = useCallback(async () => {
    if (!doc || !docId) return false;
    setSaving(true);
    setActionError(null);
    try {
      await saveSpec(client, docId, toYaml(doc));
      setBaseline(doc);
      return true;
    } catch (err) {
      setActionError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }, [client, doc, docId]);

  const resetOrDelete = useCallback(async () => {
    if (!specId) return null;
    setActionError(null);
    try {
      const reply = await deleteSpec(client, specId);
      if (reply.entry === null) return "deleted" as const;
      setReload((n) => n + 1);
      return "restored" as const;
    } catch (err) {
      setActionError(errorMessage(err));
      return null;
    }
  }, [client, specId]);

  /**
   * Export one artifact. Bytes come back in the reply and are written through
   * the user's own save dialog — the sidecar never writes outside its data dir,
   * and the dialog is what scopes the write (`capture.ts`'s pattern).
   */
  const exportArtifact = useCallback(
    async (kind: string) => {
      if (!doc || !specId) return;
      setExporting(true);
      setActionError(null);
      try {
        const reply = await exportSpec(client, specId, toYaml(doc), [kind]);
        const artifact = reply.artifacts[0];
        if (!artifact) {
          setActionError(
            "Nothing to export — every artifact except the YAML needs a spec that compiles.",
          );
          return;
        }
        const { save: pick } = await import("@tauri-apps/plugin-dialog");
        const path = await pick({ defaultPath: artifact.filename });
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
        setActionError(errorMessage(err));
      } finally {
        setExporting(false);
      }
    },
    [client, doc, specId],
  );

  return {
    doc,
    baseline,
    dirty,
    docId,
    saving,
    openError,
    actionError,
    setDoc,
    save,
    resetOrDelete,
    exportArtifact,
    exporting,
  };
}

/**
 * Presentation for a spec's chip. One definition, three surfaces.
 *
 * It used to distinguish three origins. Nothing ships as a spec, so every task
 * on a rig is that rig's own and the only thing left worth saying is whether
 * there are unsaved edits in the editor right now.
 */
export function originChip(
  _origin: SpecOrigin,
  dirty = false,
): { label: string; color: string } {
  return dirty
    ? { label: "EDITED", color: "var(--color-pulsar)" }
    : { label: "YOURS", color: "var(--color-ion)" };
}
