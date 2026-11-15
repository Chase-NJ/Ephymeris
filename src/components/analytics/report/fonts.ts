/**
 * The report sheet's fonts, inlined as data URLs (`DATA.md#exporting-a-sheet`).
 *
 * A rasterizer serializes the sheet into an SVG `<foreignObject>` and loads it
 * as an image, which is a separate document that may not load external
 * resources at all — so the faces have to travel *inside* it. Left to itself,
 * `modern-screenshot` gets there by walking `document.styleSheets` and
 * `fetch`ing every `@font-face` url it finds. Two reasons not to let it:
 *
 * `styles/fonts.ts` pulls in eight `@fontsource` stylesheets, and each ships
 * latin, latin-ext, cyrillic, cyrillic-ext, greek, greek-ext and vietnamese
 * subsets — roughly eighty files. Base64-ing all of them on every export is
 * megabytes of work for six faces of latin text.
 *
 * The second reason is the dangerous one. Dev serves over `http://localhost`,
 * but a packaged build serves over `tauri://localhost` on macOS and
 * `http://tauri.localhost` on Windows, and a custom-scheme `fetch` is exactly
 * the kind of thing that returns an opaque failure. The library's fallback for
 * a font it couldn't load is to carry on without it — so the symptom is a PNG
 * silently set in Times New Roman, and since this is developed on macOS and
 * runs on Windows, neither routine loop exercises the risky path.
 *
 * Importing the files with Vite's `?inline` sidesteps all of it: the bytes are
 * data URLs at build time, there is no request to fail, and dev and production
 * are byte-identical.
 */

import interRegular from "@fontsource/inter/files/inter-latin-400-normal.woff2?inline";
import interMedium from "@fontsource/inter/files/inter-latin-500-normal.woff2?inline";
import interSemiBold from "@fontsource/inter/files/inter-latin-600-normal.woff2?inline";
import monoRegular from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2?inline";
import monoMedium from "@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2?inline";
import displayMedium from "@fontsource/space-grotesk/files/space-grotesk-latin-500-normal.woff2?inline";
import displaySemiBold from "@fontsource/space-grotesk/files/space-grotesk-latin-600-normal.woff2?inline";
import displayBold from "@fontsource/space-grotesk/files/space-grotesk-latin-700-normal.woff2?inline";

function face(family: string, weight: number, src: string): string {
  return `@font-face{font-family:"${family}";font-style:normal;font-weight:${weight};font-display:block;src:url(${src}) format("woff2")}`;
}

/** The eight faces `styles/fonts.ts` declares, latin subset only. */
export const REPORT_FONT_CSS = [
  face("Inter", 400, interRegular),
  face("Inter", 500, interMedium),
  face("Inter", 600, interSemiBold),
  face("JetBrains Mono", 400, monoRegular),
  face("JetBrains Mono", 500, monoMedium),
  face("Space Grotesk", 500, displayMedium),
  face("Space Grotesk", 600, displaySemiBold),
  face("Space Grotesk", 700, displayBold),
].join("");
