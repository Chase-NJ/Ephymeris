import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent } from "react";

import { PanelTitle } from "@/components/charts/PanelTitle";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { TextInput } from "@/components/common/controls";
import { useCohortSessionStats } from "@/lib/analytics/useCohortSessionStats";
import type { CohortSummary } from "@/lib/cohorts/types";
import { CASCADE, RISE } from "@/lib/motion";

/** Past this many cohorts a filter field earns its row. */
const FILTER_FROM = 8;

/**
 * The cohort list Analytics and Log open on (`ARCHITECTURE.md#cohort-browser`).
 *
 * Choosing which cohort to read is a list choice, so it is drawn as one: a
 * telemetry panel of rows, most recently run first, each carrying the world's
 * disc so it is still recognisably the planet from `/cohorts`. The 3D browser
 * stays where the library is managed; here a pick IS the action.
 */
export function CohortManifest({
  cohorts,
  onPick,
}: {
  cohorts: CohortSummary[];
  onPick: (id: string) => void;
}) {
  const ids = useMemo(() => cohorts.map((c) => c.id), [cohorts]);
  const stats = useCohortSessionStats(ids);
  const [query, setQuery] = useState("");
  const list = useRef<HTMLUListElement>(null);

  // Most recently RUN first; a cohort with no sessions yet falls back to when
  // it was last edited. Instants, never names (`DATA.md#directory-layout-and-naming`).
  const ordered = useMemo(() => {
    const recency = (c: CohortSummary) =>
      stats.get(c.id)?.lastStartedAt ?? (Date.parse(c.updatedAt) || 0);
    const needle = query.trim().toLowerCase();
    return cohorts
      .filter((c) => !needle || c.name.toLowerCase().includes(needle))
      .sort((a, b) => recency(b) - recency(a));
  }, [cohorts, stats, query]);

  function step(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const rows = [...(list.current?.querySelectorAll<HTMLButtonElement>("button[data-row]") ?? [])];
    const at = rows.indexOf(event.currentTarget);
    rows[at + (event.key === "ArrowDown" ? 1 : -1)]?.focus();
  }

  if (cohorts.length === 0) return null;

  return (
    <section className="telemetry flex max-h-full min-h-0 flex-col p-4">
      <div className="mb-3 flex items-center gap-3">
        <PanelTitle
          name="Cohorts"
          note={`${cohorts.length} active · most recently run first`}
        />
        {cohorts.length > FILTER_FROM && (
          <TextInput
            label="Filter cohorts"
            value={query}
            onChange={setQuery}
            placeholder="Filter…"
            className="ml-auto w-[160px]"
          />
        )}
      </div>

      {/* Column captions, ruled like a chart axis. */}
      <div className="grid grid-cols-[28px_minmax(0,1fr)_auto_64px_96px_16px] items-center gap-x-4 border-b border-halo/80 px-2 pb-1.5 font-mono text-[9px] tracking-[0.16em] text-static/70 uppercase">
        <span />
        <span>Name</span>
        <span>Roster</span>
        <span className="text-right">Sessions</span>
        <span className="text-right">Last run</span>
        <span />
      </div>

      <motion.ul
        ref={list}
        variants={CASCADE}
        initial="hidden"
        animate="shown"
        className="scrollbar-none -mx-px min-h-0 overflow-y-auto pt-1"
      >
        {ordered.map((cohort) => {
          const s = stats.get(cohort.id);
          return (
            <motion.li key={cohort.id} variants={RISE}>
              <button
                type="button"
                data-row
                onClick={() => onPick(cohort.id)}
                onKeyDown={step}
                className="group grid w-full grid-cols-[28px_minmax(0,1fr)_auto_64px_96px_16px] items-center gap-x-4 border-y border-transparent px-2 py-2 text-left transition-colors hover:border-pulsar/40 hover:bg-pulsar/[0.07] focus:outline-none focus-visible:border-pulsar/40 focus-visible:bg-pulsar/[0.07]"
              >
                <PlanetDisc cohortId={cohort.id} appearance={cohort.appearance} size={24} />
                <span className="truncate text-[13px] text-starlight">{cohort.name}</span>
                <span className="font-mono text-[11px] text-static tabular-nums">
                  {plural(cohort.animalCount, "animal")} · {plural(cohort.groupCount, "group")} ·{" "}
                  {plural(cohort.cageCount, "cage")}
                </span>
                <span className="text-right font-mono text-[11px] text-starlight tabular-nums">
                  {s ? s.sessions : <span className="text-static/50">—</span>}
                </span>
                <span className="text-right font-mono text-[11px] text-static tabular-nums">
                  {s?.lastDate ? shortDate(s.lastDate) : <span className="text-static/50">—</span>}
                </span>
                <ArrowRight
                  size={13}
                  strokeWidth={1.75}
                  className="-translate-x-1 text-pulsar opacity-0 transition-[opacity,transform] group-hover:translate-x-0 group-hover:opacity-100 group-focus-visible:translate-x-0 group-focus-visible:opacity-100"
                />
              </button>
            </motion.li>
          );
        })}
        {ordered.length === 0 && (
          <li className="px-2 py-3 text-[12px] text-static">No cohort matches “{query}”.</li>
        )}
      </motion.ul>
    </section>
  );
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** `6 Oct 2026` from a calendar day, read without a zone. */
function shortDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
