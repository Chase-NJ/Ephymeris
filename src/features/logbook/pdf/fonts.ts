/**
 * The faces a PDF embeds, inlined at build time.
 *
 * `.woff`, not the `.woff2` the screen and the PNG sheet use: react-pdf's font
 * engine reads TrueType and WOFF, and `@fontsource` ships both. Inlined with
 * Vite's `?inline` for `report/fonts.ts`'s reason — a fetch over the packaged
 * app's custom scheme fails silently, and the symptom would be a PDF set in
 * Helvetica that nobody notices until it is printed.
 */

import { Font } from "@react-pdf/renderer";

import interRegular from "@fontsource/inter/files/inter-latin-400-normal.woff?inline";
import interMedium from "@fontsource/inter/files/inter-latin-500-normal.woff?inline";
import interSemiBold from "@fontsource/inter/files/inter-latin-600-normal.woff?inline";
import monoRegular from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff?inline";
import monoMedium from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff?inline";
import displayMedium from "@fontsource/space-grotesk/files/space-grotesk-latin-500-normal.woff?inline";
import displaySemiBold from "@fontsource/space-grotesk/files/space-grotesk-latin-600-normal.woff?inline";
import interExt from "@fontsource/inter/files/inter-latin-ext-400-normal.woff?inline";
import interGreek from "@fontsource/inter/files/inter-greek-400-normal.woff?inline";

import { FONT } from "./theme";

let registered = false;

export function registerFonts(): void {
  if (registered) return;
  registered = true;
  Font.register({
    family: FONT.sans,
    fonts: [
      { src: interRegular, fontWeight: 400 },
      { src: interMedium, fontWeight: 500 },
      { src: interSemiBold, fontWeight: 600 },
    ],
  });
  Font.register({
    family: FONT.mono,
    fonts: [
      { src: monoRegular, fontWeight: 400 },
      { src: monoMedium, fontWeight: 500 },
    ],
  });
  Font.register({
    family: FONT.display,
    fonts: [
      { src: displayMedium, fontWeight: 500 },
      { src: displaySemiBold, fontWeight: 600 },
    ],
  });
  // Fallback faces, one weight each: accented names (Łukasz, Dvořák) and Greek
  // (ΔF/F, τ) in notes. react-pdf picks, per glyph, the first family in a
  // style's `fontFamily` list that has it (`FALLBACK` in `theme.ts`).
  Font.register({ family: FONT.sansExt, src: interExt });
  Font.register({ family: FONT.sansGreek, src: interGreek });
  // Session names and parameter keys are identifiers: never hyphenate them.
  Font.registerHyphenationCallback((word) => [word]);
}
