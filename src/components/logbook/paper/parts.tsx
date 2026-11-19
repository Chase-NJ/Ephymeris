import type { ReactNode } from "react";

import type { SiteVerdict } from "@/lib/logbook/signal";
import type { NoteTag } from "@/lib/logbook/types";

/**
 * The small things every page of the notebook is set from
 * (`ARCHITECTURE.md#the-paper-exception`).
 */

/**
 * Per-animal identity on paper. The app's own series ramp is tuned for Void
 * and washes out on a light ground, so the page has its own six, in the same
 * order: the animal that is series 1 everywhere else is series 1 here. Checked
 * against Paper for colour-blind separation between neighbours (worst pair
 * ΔE 12.1 deutan), normal-vision separation (23.3) and 3:1 contrast.
 */
export const PAPER_SERIES = [
  "#6652c8",
  "#0d8f80",
  "#cf4a2e",
  "#2d7ad1",
  "#b07f00",
  "#a13d90",
] as const;

/** Roster position picks the colour, as `buildAnimalColors` does for the dark screens. */
export function paperAnimalColors(animals: ReadonlyArray<{ id: string }>): Map<string, string> {
  return new Map(
    animals.map((animal, index) => [animal.id, PAPER_SERIES[index % PAPER_SERIES.length]!]),
  );
}

/** The ink each kind of note is labelled in. The label's word still says the kind. */
export const TAG_INK: Record<NoteTag, string> = {
  observation: "var(--color-ink-blue)",
  intervention: "var(--color-ink-plum)",
  hardware: "var(--color-ink-ochre)",
  "animal-health": "var(--color-ink-teal)",
  "protocol-deviation": "var(--color-ink-red)",
};

/** `\section`: a number in the pen's blue, then the title. */
export function SectionHead({
  number,
  children,
  aside,
}: {
  /** Absent in the front matter, whose sections are unnumbered. */
  number?: number;
  children: ReactNode;
  /** Set at the right of the line: a count, or a way out to another screen. */
  aside?: ReactNode;
}) {
  return (
    <div className="mt-6 mb-2 flex items-baseline gap-2.5 first:mt-1">
      <h3 className="text-[18px] leading-tight font-bold">
        {number !== undefined && <span className="mr-2.5 text-ink-blue">{number}</span>}
        {children}
      </h3>
      {aside && <span className="ml-auto text-[13px] text-ink-soft">{aside}</span>}
    </div>
  );
}

/** `\caption`, set above its table as a table's is. */
export function Caption({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p className="mb-1.5 text-[13px] leading-snug text-ink-soft">
      <span className="font-bold text-ink">{label}.</span> {children}
    </p>
  );
}

/** A table's footnote: what a mark in it means, or what it leaves out. */
export function Footnote({ children }: { children: ReactNode }) {
  return <p className="mt-1.5 text-[12.5px] leading-snug text-ink-soft">{children}</p>;
}

/** An animal's name behind its identity dot. */
export function AnimalMark({
  name,
  color,
  strong = true,
}: {
  name: string;
  color: string | undefined;
  strong?: boolean;
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span
        aria-hidden
        className="inline-block size-[9px] shrink-0 translate-y-[-1px] rounded-full"
        style={{ backgroundColor: color ?? "var(--color-rule)" }}
      />
      <span className={strong ? "font-bold" : ""} data-selectable>
        {name}
      </span>
    </span>
  );
}

/**
 * A trend in a table cell: one series, so no legend and no axis; the last
 * point is the one the row is about and carries the dot. The values are in
 * the hover title, which is the cell's table view.
 */
export function Sparkline({
  values,
  title,
  color,
  floor,
  width = 68,
  height = 20,
}: {
  values: readonly number[];
  title: string;
  /** The last point's dot; the line itself stays in ink. */
  color?: string | undefined;
  /** A value the scale must include, drawn as a dashed rule: a weight's floor. */
  floor?: number | undefined;
  width?: number;
  height?: number;
}) {
  if (values.length === 0) return null;
  const pad = 3;
  const all = floor === undefined ? [...values] : [...values, floor];
  const low = Math.min(...all);
  const high = Math.max(...all);
  const span = high - low || 1;
  const x = (index: number) =>
    values.length === 1 ? width - pad : pad + (index * (width - 2 * pad)) / (values.length - 1);
  const y = (value: number) => height - pad - ((value - low) / span) * (height - 2 * pad);
  const points = values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`);
  const last = values[values.length - 1]!;
  return (
    <svg
      role="img"
      aria-label={title}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="inline-block align-middle"
    >
      <title>{title}</title>
      {floor !== undefined && (
        <line
          x1={pad}
          x2={width - pad}
          y1={y(floor)}
          y2={y(floor)}
          stroke="var(--color-ink-red)"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}
      {values.length > 1 && (
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke="var(--color-ink-soft)"
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}
      <circle
        cx={x(values.length - 1)}
        cy={y(last)}
        r={2.75}
        fill={color ?? "var(--color-ink-soft)"}
        stroke="var(--color-paper)"
        strokeWidth={1}
      />
    </svg>
  );
}

const SITE_PX = 7;
const SITE_GAP = 2;
/** Sites per row: one bundle of the lab's 32-channel electrode. */
const SITES_PER_ROW = 16;

/**
 * An animal's electrode sites, one square each, in RHX's order. One hue on
 * one scale, because the three classes are one scale: solid is unit-like,
 * pale is merely active, hollow is quiet. Shape repeats what the shade says,
 * so it survives a greyscale print.
 */
export function SiteStrip({ sites }: { sites: readonly SiteVerdict[] }) {
  const columns = Math.min(SITES_PER_ROW, sites.length);
  const rows = Math.ceil(sites.length / SITES_PER_ROW);
  const width = columns * (SITE_PX + SITE_GAP) - SITE_GAP;
  const height = rows * (SITE_PX + SITE_GAP) - SITE_GAP;
  return (
    <svg
      role="img"
      aria-label={`${sites.filter((s) => s.cls === "unit").length} of ${sites.length} sites unit-like`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="inline-block align-middle"
    >
      {sites.map((site, index) => {
        const x = (index % SITES_PER_ROW) * (SITE_PX + SITE_GAP);
        const y = Math.floor(index / SITES_PER_ROW) * (SITE_PX + SITE_GAP);
        const quiet = site.cls === "quiet";
        return (
          <rect
            key={site.channel}
            x={quiet ? x + 0.5 : x}
            y={quiet ? y + 0.5 : y}
            width={quiet ? SITE_PX - 1 : SITE_PX}
            height={quiet ? SITE_PX - 1 : SITE_PX}
            rx={1.5}
            fill={
              site.cls === "unit"
                ? "var(--color-ink-plum)"
                : site.cls === "active"
                  ? "color-mix(in srgb, var(--color-ink-plum) 38%, var(--color-paper))"
                  : "none"
            }
            stroke={quiet ? "var(--color-rule)" : "none"}
            strokeWidth={1}
          >
            <title>{siteTitle(site)}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function siteTitle(site: SiteVerdict): string {
  const kind =
    site.cls === "unit" ? "unit-like" : site.cls === "active" ? "active, not unit-like" : "quiet";
  const parts = [`${site.channel}: ${kind}`];
  if (site.unitHz !== null) parts.push(`${site.unitHz.toFixed(2)} Hz of large spikes`);
  if (site.rateHz !== null) parts.push(`${site.rateHz.toFixed(2)} Hz in all`);
  if (site.noiseUv !== null) parts.push(`noise ${site.noiseUv.toFixed(1)} µV`);
  return parts.join(" · ");
}
