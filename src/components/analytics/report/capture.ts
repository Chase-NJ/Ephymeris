import { save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import { domToBlob } from "modern-screenshot";

import { REPORT_FONT_CSS } from "./fonts";

/**
 * Rasterize a report sheet and write it where the user asks (`data.md` §10.6).
 *
 * Shell-side rather than a sidecar command, for the same reasons the debug-log
 * save is (`debug/NodeDetail.tsx`): the dialog plugin adds the chosen path to
 * the fs scope at runtime, and nothing here belongs in the data pipeline. The
 * sheet is a picture of numbers the sidecar already computed — re-deriving it
 * there would mean a second implementation of every chart, which is precisely
 * what this design exists to avoid.
 */

/**
 * Rendered at 1× on purpose.
 *
 * Every chart in this app strokes with `vector-effect="non-scaling-stroke"`,
 * which resolves line weight in screen space rather than user space. Scaling
 * the raster is exactly the operation that makes screen space and user space
 * disagree, and `data.md` §10.5 already records what that does to these charts.
 * A 1280-wide sheet is several thousand pixels tall, which is plenty for a
 * slide or a notebook, so there is nothing to buy by risking it.
 */
const SCALE = 1;

/** The sheet's right-hand padding, restored when it is widened to fit. */
const GUTTER = 32;

export async function captureSheet(node: HTMLElement): Promise<Blob> {
  // The faces have to be resident before the clone measures text, or the
  // layout is taken against a fallback metric.
  await document.fonts.ready;
  // Framer paints an element's `initial` on the frame it mounts and its
  // settled value on the next. `skipAnimations` removes the tween, not that
  // first frame — so one turn of the loop is genuinely necessary and two is
  // the cheap margin.
  await nextFrame();
  await nextFrame();

  // The heatmap sizes itself in fixed pixels per session (see its
  // `MIN_PX_PER_COLUMN`), so a long-running cohort makes one row wider than
  // the sheet. Rasterizing measures the node's own box, which would cut the
  // most recent sessions off the right edge — the ones being looked for. The
  // sheet is ours alone and not yet visible to anyone, so widening it here is
  // cheaper and less brittle than teaching the layout to predict the heatmap's
  // arithmetic. `scrollWidth` omits the trailing padding, hence the gutter.
  if (node.scrollWidth > node.clientWidth) {
    node.style.width = `${node.scrollWidth + GUTTER}px`;
    await nextFrame();
  }

  return domToBlob(node, {
    scale: SCALE,
    type: "image/png",
    // The page's background lives on `body`, which is outside the captured
    // node — without this the PNG has a transparent hole behind every gap
    // between the cards.
    backgroundColor: getComputedStyle(node).backgroundColor || "#0b0b10",
    font: { cssText: REPORT_FONT_CSS },
  });
}

/**
 * Ask for a path and write the bytes. Resolves to the path, or `null` if the
 * user cancelled — which is an outcome, not an error.
 */
export async function saveSheet(blob: Blob, defaultName: string): Promise<string | null> {
  const path = await save({
    defaultPath: defaultName,
    filters: [{ name: "PNG image", extensions: ["png"] }],
  });
  if (!path) return null;
  await writeFile(path, new Uint8Array(await blob.arrayBuffer()));
  return path;
}

/**
 * One paint, or a short wait if there won't be one.
 *
 * `requestAnimationFrame` does not fire while the window is hidden, and an
 * export is exactly the kind of thing someone starts and then alt-tabs away
 * from. Waiting on it alone leaves the button stuck on "Exporting…" and the
 * sheet mounted for as long as the app stays in the background — a hang with
 * no way out but a restart. The timer is the floor, not the plan: whenever
 * there is a frame coming it wins the race and nothing waits the full 50ms.
 */
function nextFrame(): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    requestAnimationFrame(finish);
    setTimeout(finish, 50);
  });
}

/** Anything that would be awkward in a filename, collapsed to a dash. */
export function slug(value: string): string {
  return (
    value
      .trim()
      .replace(/[^\w.-]+/g, "-")
      .replace(/-{2,}/g, "-")
      .replace(/^-|-$/g, "") || "untitled"
  );
}
