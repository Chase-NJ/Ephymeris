/**
 * The main window's opening size: 4/5 of the display it opens on, never below
 * the minimum.
 *
 * A fixed pixel size cannot serve both the dev Mac and the lab PCs: the same
 * 1280x820 is most of one screen and a small square on another. Pure, so the
 * clamp (what bites on a small screen) is tested without a monitor.
 */

export const MIN_WIDTH = 1024;
export const MIN_HEIGHT = 700;

const FRACTION = 4 / 5;

/** For a display of the given size in DIPs (Electron's `Display.size`). */
export function openingSize(screenWidth: number, screenHeight: number): { width: number; height: number } {
  return {
    width: Math.round(Math.max(screenWidth * FRACTION, MIN_WIDTH)),
    height: Math.round(Math.max(screenHeight * FRACTION, MIN_HEIGHT)),
  };
}
