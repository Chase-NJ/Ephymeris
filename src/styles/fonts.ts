/**
 * Self-hosted faces, per `ARCHITECTURE.md#theme`.
 *
 * Bundled rather than fetched from a CDN: lab PCs are expected to run without
 * internet, and a font that silently falls back would take the theme's
 * typographic identity with it. Weights are enumerated rather than imported
 * wholesale so the bundle carries only what the design actually uses.
 */

// Display — headers only.
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";

// Body / UI.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";

// Mono / data — console text, timestamps, port names, IDs.
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
