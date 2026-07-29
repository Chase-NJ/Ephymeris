/**
 * Turning what someone types into a roster.
 *
 * Adding animals one blank row at a time is the slowest part of setting a
 * cohort up, and lab rosters already exist somewhere else — a column in a
 * spreadsheet, a line in a protocol, or a naming scheme in someone's head.
 * This parses all three shapes into names, so the fast path is paste-and-go.
 *
 * Pure on purpose: the component that calls it stays about rendering, and the
 * fiddly half (what counts as a separator, what a `×` means) is readable in
 * one place.
 */

/** `R- × 8`, `R-x8`, `Rat *3` — a prefix and how many of it. */
const RUN_RE = /^\s*(.+?)\s*[×x*]\s*(\d+)\s*$/i;

/** A run longer than this is a typo, not a cohort. */
const MAX_RUN = 200;

export interface RosterParse {
  /** Names to add, in order, already trimmed and internally deduped. */
  names: string[];
  /** Names dropped because the cohort already has them, case-insensitively. */
  duplicates: string[];
}

/**
 * Parse a bulk-add field against the names already present.
 *
 * Duplicates are dropped rather than added, because the sidecar rejects
 * cohort-wide duplicate names (`repository.py`'s `_validate`) — pasting the
 * same column twice would otherwise turn the whole roster red instead of
 * quietly doing nothing, which is what the user meant by it.
 */
export function parseRoster(input: string, existing: Iterable<string>): RosterParse {
  const taken = new Set(
    [...existing].map((n) => n.trim().toLowerCase()).filter((n) => n !== ""),
  );
  const names: string[] = [];
  const duplicates: string[] = [];

  for (const candidate of expand(input)) {
    const key = candidate.toLowerCase();
    if (taken.has(key)) {
      duplicates.push(candidate);
      continue;
    }
    taken.add(key);
    names.push(candidate);
  }

  return { names, duplicates };
}

/** The raw candidates a field yields, before any duplicate check. */
function expand(input: string): string[] {
  const run = RUN_RE.exec(input);
  if (run) {
    const prefix = run[1]!.trim();
    const count = Math.min(Number(run[2]), MAX_RUN);
    // 1-based: the lab counts animals from one, and `R-0` reads as a mistake.
    return Array.from({ length: count }, (_, i) => `${prefix}${i + 1}`);
  }

  // Commas, newlines, and tabs — a spreadsheet column pastes as any of the
  // three depending on where it came from.
  return input
    .split(/[,\n\t]/)
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

/** What the field's hint says about what will happen if you commit it now. */
export function rosterPreview(input: string, existing: Iterable<string>): string | null {
  if (input.trim() === "") return null;
  const { names, duplicates } = parseRoster(input, existing);
  const parts: string[] = [];
  if (names.length > 0) {
    parts.push(
      names.length <= 3
        ? `Adds ${names.join(", ")}`
        : `Adds ${names.length} animals — ${names[0]} … ${names[names.length - 1]}`,
    );
  }
  if (duplicates.length > 0) {
    parts.push(
      `${duplicates.length} already in this cohort ${
        duplicates.length === 1 ? "is" : "are"
      } skipped`,
    );
  }
  return parts.join(" · ") || null;
}
