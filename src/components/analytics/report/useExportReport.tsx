import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useAnalyticsStore } from "@/lib/analytics/context";
import { SAVE_STEPS, trackExport } from "@/lib/exports/jobs";

import { captureSheet, saveSheet, slug } from "./capture";
import { ReportSheet, type ReportInput } from "./ReportSheet";

/**
 * Mount a report sheet, rasterize it, save it, take it back down
 * (`DATA.md#exporting-a-sheet`).
 *
 * Returns the portal to render and a `run` to call. The caller renders
 * `portal` unconditionally; it is `null` except during an export. Progress,
 * the saved path and any failure are reported on the export card
 * (`ARCHITECTURE.md#export-progress`), not here.
 */
const PREPARING = "Preparing the sheet";
const RENDERING = "Rendering";

export function useExportReport() {
  const store = useAnalyticsStore();
  const [pending, setPending] = useState<ReportInput | null>(null);
  const [busy, setBusy] = useState(false);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const readyRef = useRef<(() => void) | null>(null);
  // Guards a second click while the first export is still in the air, and
  // StrictMode's double-invoked effects in development.
  const runningRef = useRef(false);

  // The sheet is in the document and laid out — hand control back to `run`.
  useEffect(() => {
    if (!pending || !sheetRef.current) return;
    const resolve = readyRef.current;
    readyRef.current = null;
    resolve?.();
  }, [pending]);

  const run = useCallback(
    async (input: ReportInput, filename: string) => {
      if (runningRef.current) return;
      runningRef.current = true;
      setBusy(true);

      // A pinned animal dims every other one to near-invisibility across the
      // strategy planes, the learning curves and both accuracy trends — it is
      // the dashboard's "show me this one" mode, and it would export as a
      // figure that is mostly blank. Cleared for the duration and put back
      // afterwards, since the reader did not ask to lose their selection.
      const pinned = store.getPinnedAnimal();
      if (pinned) store.selectAnimal(null);

      try {
        await trackExport(
          input.session ? "Session PNG" : "Cohort PNG",
          "image",
          [PREPARING, RENDERING, ...SAVE_STEPS],
          async (tracker) => {
            await new Promise<void>((resolve) => {
              readyRef.current = resolve;
              setPending(input);
            });
            const node = sheetRef.current;
            if (!node) throw new Error("the report sheet did not mount");

            tracker.step(RENDERING);
            const blob = await captureSheet(node, (fraction) => tracker.progress(fraction));
            return saveSheet(blob, filename, tracker);
          },
        );
      } catch {
        // On the card already; nothing more to say here.
      } finally {
        setPending(null);
        if (pinned) store.selectAnimal(pinned);
        setBusy(false);
        runningRef.current = false;
      }
    },
    [store],
  );

  const portal: ReactNode = pending
    ? createPortal(
        // Off the side of the window rather than hidden. `display: none` has
        // no layout to measure and `visibility: hidden` is faithfully copied
        // onto the clone — both rasterize to nothing. Moving it out of view
        // leaves a fully laid-out, fully painted subtree that simply isn't
        // where anyone is looking.
        //
        // A portal, but still inside the React tree, so the panels keep the
        // analytics store, the sidecar client and the settings they expect.
        <div
          aria-hidden
          style={{
            position: "fixed",
            top: 0,
            left: -20000,
            pointerEvents: "none",
            zIndex: -1,
          }}
        >
          <ReportSheet input={pending} ref={sheetRef} />
        </div>,
        document.body,
      )
    : null;

  return { run, portal, busy };
}

/**
 * What the file gets called. Cohort leads so a folder of these sorts into
 * something readable, and the date is ISO for the same reason. No task in the
 * name any more — the sheet spans every task the archive holds.
 */
export function reportFilename(input: ReportInput): string {
  const parts = [slug(input.cohortName)];
  if (input.session) {
    parts.push(
      `${slug(input.session.prefixName)}-${slug(input.session.sessionNumber)}`,
      slug(input.session.date),
    );
  } else {
    parts.push("all-sessions", new Date().toISOString().slice(0, 10));
  }
  return `${parts.join("_")}.png`;
}
