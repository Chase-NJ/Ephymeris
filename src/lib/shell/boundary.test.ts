import { describe, expect, it } from "vitest";

/**
 * The webview reaches the desktop shell only through `lib/shell`
 * (`ARCHITECTURE.md#the-shell-module`), so changing shells is one new
 * implementation there rather than an edit in every screen that saves a file
 * or opens a window (ADR 0006). This fails on any other file that reads the
 * Electron preload's bridge or imports the `electron` package. Sources come in through Vite's own glob, as text, so the
 * test needs no Node types.
 */

const SOURCES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/**
 * What only one file may touch, and that file (null: none may). This test
 * names them too, but Vite's glob never includes the module doing the globbing.
 */
const RULES: Array<{ what: string; pattern: RegExp; home: string | null }> = [
  { what: "window.ephymeris", pattern: /\bwindow\.ephymeris\b/, home: "/src/lib/shell/electron.ts" },
  // Main-process code: a page that imported it would not even load.
  {
    what: "the electron package",
    pattern: /(?:from|import\(|mock\(|require\()\s*["'`]electron(?:\/[^"'`]*)?["'`]/,
    home: null,
  },
];

describe("the shell boundary", () => {
  it("sees the source tree (or this test is checking nothing)", () => {
    for (const { pattern, home } of RULES) {
      if (home === null) continue;
      expect(home in SOURCES, home).toBe(true);
      expect(pattern.test(SOURCES[home]!), home).toBe(true);
    }
  });

  for (const { what, pattern, home } of RULES) {
    it(`touches ${what} ${home ? `only in ${home}` : "nowhere"}`, () => {
      const offenders = Object.entries(SOURCES)
        .filter(([file, text]) => file !== home && pattern.test(text))
        .map(([file]) => file);
      expect(offenders, `go through @/lib/shell instead:\n  ${offenders.join("\n  ")}`).toEqual([]);
    });
  }
});
