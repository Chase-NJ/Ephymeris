import { Search } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import { Segmented } from "@/components/common/controls";
import type { StrobeVocabulary } from "@/lib/ws/protocol";

export type StrobeFilter = "live" | "retired" | "all";

/** One row, live or retired, in the shape the table and the detail share. */
export interface StrobeRow {
  name: string;
  code: number;
  status: "live" | "retired";
  meaning: string;
  emittedOn?: string | undefined;
  origin?: string | undefined;
  portSlot?: number | undefined;
  seenIn?: string | undefined;
  retiredAt?: string | undefined;
}

/** Whether `code` falls in any inclusive `[lo, hi]` pair the wire sends. */
export function inRanges(ranges: number[][], code: number): boolean {
  return ranges.some(([lo = 0, hi = -1]) => code >= lo && code <= hi);
}

/** How many codes the inclusive `[lo, hi]` pairs cover. */
export function rangeSize(ranges: number[][]): number {
  return ranges.reduce((n, [lo = 0, hi = -1]) => n + hi - lo + 1, 0);
}

export function rowsOf(vocabulary: StrobeVocabulary): StrobeRow[] {
  return [
    ...vocabulary.codes.map(
      (c): StrobeRow => ({
        name: c.name,
        code: c.code,
        status: "live",
        meaning: c.rationale ?? "",
        emittedOn: c.emittedOn,
        origin: c.origin,
        portSlot: c.portSlot,
      }),
    ),
    ...vocabulary.retired.map(
      (c): StrobeRow => ({
        name: c.name,
        code: c.code,
        status: "retired",
        meaning: c.rationale ?? "",
        seenIn: c.seenIn,
        retiredAt: c.retiredAt,
      }),
    ),
  ].sort((a, b) => a.code - b.code);
}

/**
 * The vocabulary as a list, by code.
 *
 * ONE TABLE, FILTERED, rather than a live table and a retired one stacked: a
 * retired code sits where its number does, between the live codes it was
 * issued among, so the gap it leaves in a run (110–113 in the odor onsets) is
 * in the place a reader goes looking for it.
 */
export function StrobeTable({
  rows,
  filter,
  query,
  selected,
  onFilter,
  onQuery,
  onSelect,
}: {
  rows: StrobeRow[];
  filter: StrobeFilter;
  query: string;
  selected: string | null;
  onFilter: (next: StrobeFilter) => void;
  onQuery: (next: string) => void;
  onSelect: (name: string) => void;
}) {
  const counts = useMemo(
    () => ({
      live: rows.filter((r) => r.status === "live").length,
      retired: rows.filter((r) => r.status === "retired").length,
    }),
    [rows],
  );

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (filter === "all" || r.status === filter) &&
        (!q ||
          r.name.toLowerCase().includes(q) ||
          String(r.code).startsWith(q) ||
          r.meaning.toLowerCase().includes(q) ||
          (r.emittedOn ?? "").toLowerCase().includes(q)),
    );
  }, [rows, filter, query]);

  // A row selected from the code band may be scrolled out of sight; bring it
  // in, without moving a row that is already visible.
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!selected) return;
    const el = list.current?.querySelector<HTMLElement>(`[data-name="${selected}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selected, filter]);

  return (
    <section className="hud flex min-h-0 flex-col rounded-md">
      <header className="flex flex-wrap items-center gap-2 border-b border-halo px-3 py-2">
        <Segmented
          label="Which codes"
          value={filter}
          onChange={onFilter}
          options={[
            { value: "live", label: `Live ${counts.live}` },
            { value: "retired", label: `Retired ${counts.retired}` },
            { value: "all", label: "All" },
          ]}
        />
        <label className="ml-auto flex items-center gap-1.5 rounded-sm border border-halo bg-nebula px-2 py-1 focus-within:border-pulsar">
          <Search size={12} strokeWidth={1.75} className="text-static" />
          <input
            type="text"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Name, number or meaning"
            aria-label="Filter codes"
            className="w-48 bg-transparent text-[11.5px] text-starlight placeholder:text-static/60 focus:outline-none"
          />
        </label>
      </header>

      <div
        ref={list}
        className="scrollbar-none min-h-0 flex-1 overflow-y-auto"
        role="listbox"
        aria-label="Strobe codes"
      >
        {shown.length === 0 && (
          <p className="px-3.5 py-6 text-center text-[11px] text-static">
            {rows.length === 0 ? "No codes." : "Nothing matches."}
          </p>
        )}
        {shown.map((row) => {
          const active = row.name === selected;
          return (
            <button
              key={row.name}
              data-name={row.name}
              type="button"
              role="option"
              aria-selected={active}
              onClick={() => onSelect(row.name)}
              className={`grid w-full grid-cols-[3.25rem_minmax(9rem,13rem)_1fr_auto] items-baseline gap-x-3 border-b border-l-2 border-b-halo/40 px-3 py-1.5 text-left text-[11px] transition-colors last:border-b-0 ${
                active
                  ? "border-l-pulsar bg-halo/45"
                  : "border-l-transparent hover:bg-halo/25"
              }`}
            >
              <span
                className={`text-right font-mono ${row.status === "live" ? "text-static" : "text-static/50"}`}
              >
                {row.code}
              </span>
              <span
                className={`truncate font-mono ${
                  row.status === "live" ? "text-starlight" : "text-static line-through decoration-static/40"
                }`}
              >
                {row.name}
              </span>
              <span className="truncate text-static/75">{row.emittedOn || row.meaning}</span>
              <span className="flex items-center gap-1">
                {row.portSlot !== undefined && <Chip>slot {row.portSlot}</Chip>}
                {row.status === "retired" ? (
                  <Chip>retired</Chip>
                ) : (
                  row.origin === "operator" && <Chip>added here</Chip>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-[3px] border border-halo px-1.5 py-px font-mono text-[9.5px] whitespace-nowrap text-static">
      {children}
    </span>
  );
}
