/**
 * The editor's page arrangement — `TASKS.md#editor`. The promise under
 * test is the floor: at every page width the app's window allows, the diagram's
 * host is at least `EDITOR_MIN_W`, so the drawing never has to scale.
 */

import { describe, expect, it } from "vitest";

import { EDITOR_MIN_W, FALLBACK_W, MAX_W, WIDTH_STEP, layoutWidthFor } from "./graphLayout";
import { diagramWidth, editorLayout } from "./editorLayout";

/** `main` reserves its scrollbar track (`AppShell`) whether or not it shows. */
const GUTTER = 10;
/** The window's `minWidth` (tauri.conf.json) less the 200px sidebar. */
const NARROWEST_PAGE = 1024 - 200 - GUTTER;

describe("editorLayout", () => {
  it("never leaves the diagram less than its floor", () => {
    for (let page = NARROWEST_PAGE; page <= 3000; page += 4) {
      const { spine, rail } = editorLayout(page);
      expect(diagramWidth(page, spine, rail), `page ${page}`).toBeGreaterThanOrEqual(EDITOR_MIN_W);
    }
  });

  it("gives up the spine before the side rail", () => {
    const modes: string[] = [];
    for (let page = 3000; page >= NARROWEST_PAGE; page -= 4) {
      const { mode } = editorLayout(page);
      if (modes.at(-1) !== mode) modes.push(mode);
    }
    expect(modes).toEqual(["wide", "medium", "stacked"]);
  });

  it("keeps the rail at the side on the default 1280px window", () => {
    expect(editorLayout(1280 - 200 - GUTTER).mode).toBe("medium");
  });

  it("docks the rail only when it has no side", () => {
    expect(editorLayout(NARROWEST_PAGE)).toMatchObject({ mode: "stacked", rail: 0 });
  });
});

describe("layoutWidthFor", () => {
  it("clamps to the floor it is given and snaps to the step", () => {
    expect(layoutWidthFor(300, EDITOR_MIN_W)).toBe(EDITOR_MIN_W);
    expect(layoutWidthFor(EDITOR_MIN_W + WIDTH_STEP - 1, EDITOR_MIN_W)).toBe(EDITOR_MIN_W);
    expect(layoutWidthFor(5000, EDITOR_MIN_W)).toBe(MAX_W);
    expect(layoutWidthFor(null)).toBe(FALLBACK_W);
  });

  it("never draws wider than its host inside the band", () => {
    for (let host = EDITOR_MIN_W; host <= MAX_W; host += 7) {
      expect(layoutWidthFor(host, EDITOR_MIN_W)).toBeLessThanOrEqual(host);
    }
  });
});
