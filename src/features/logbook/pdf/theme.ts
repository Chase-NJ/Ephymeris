/**
 * The printed log's palette — the theme's tokens carried onto paper
 * (`ARCHITECTURE.md#printed-documents`).
 *
 * The app is dark-only; a page is not a screen. Printed white-on-Void wastes a
 * cartridge and photocopies to mud, so a PDF inverts the roles: paper is the
 * background, Void is the ink. Every other colour is a token darkened only as
 * far as small text on white needs to clear WCAG AA (4.5:1), and kept on the
 * token's hue so the page still reads as Ephymeris. Pulsar stays flat — no
 * gradients on paper either — and status colours still mean state only.
 */
export const PAPER = {
  paper: "#ffffff",
  /** Void, as ink. */
  ink: "#0b0b10",
  /** Static, darkened to about 6.8:1 on white for small labels. */
  muted: "#5d5871",
  /** Halo, lightened: hairlines and table rules. */
  rule: "#dcd9e6",
  /** A row band, the faintest lift off the page. */
  band: "#f5f4f9",
  /** Pulsar, as the theme defines it — large figures and rules only. */
  pulsar: "#8b7ec8",
  /** Pulsar darkened to about 7:1, for small accent text (T+ offsets). */
  pulsarInk: "#5b4f9a",
  /** status-warning, darkened to about 6:1 for text: an open flag. */
  warning: "#8a5414",
} as const;

export const FONT = {
  display: "Space Grotesk",
  sans: "Inter",
  mono: "JetBrains Mono",
  sansExt: "Inter Latin Ext",
  sansGreek: "Inter Greek",
} as const;

/** Appended to every family list, so a glyph the primary face's latin subset
 *  lacks comes from a face that has it rather than printing as the wrong one. */
export const FALLBACK = [FONT.sansExt, FONT.sansGreek];

/** Family lists for styles: the face, then the fallbacks. */
export const FAMILY = {
  sans: [FONT.sans, ...FALLBACK],
  mono: [FONT.mono, ...FALLBACK],
  display: [FONT.display, ...FALLBACK],
};
