/**
 * Judging electrode impedances (`RECORDING.md#impedance-tracking`). Pure.
 *
 * The sidecar measures and keeps each animal's history; what counts as a bad
 * site is the lab's call, so the bounds are a recording default
 * (`RecordingDefaults.impedanceFlags`) and judged here. A site is flagged:
 *
 *   - **open** above `openOhms` — a broken lead or a site out of tissue;
 *   - **short** below `shortOhms` — bridged to a neighbour or to ground;
 *   - **changed** when it moved by more than `changeFactor` either way since
 *     that animal's previous measurement — healthy now, but going somewhere.
 *
 * Open and short win over changed: they say what is wrong, not just that
 * something moved.
 */

import type { ImpedanceComparison, ImpedanceMeasurement } from "@/lib/ws/protocol";

export type ImpedanceFlags = {
  openOhms: number;
  shortOhms: number;
  /** A ratio above 1: 2 flags a site that doubled or halved. */
  changeFactor: number;
};

export const DEFAULT_IMPEDANCE_FLAGS: ImpedanceFlags = {
  openOhms: 5e6,
  shortOhms: 20e3,
  changeFactor: 2,
};

export type SiteVerdict = "open" | "short" | "changed" | "ok";

export function siteVerdict(ohms: number, previousOhms: number | null, flags: ImpedanceFlags): SiteVerdict {
  if (ohms > flags.openOhms) return "open";
  if (ohms < flags.shortOhms) return "short";
  if (previousOhms !== null && previousOhms > 0) {
    const ratio = ohms / previousOhms;
    if (ratio > flags.changeFactor || ratio < 1 / flags.changeFactor) return "changed";
  }
  return "ok";
}

export type SiteJudgement = {
  channel: string;
  ohms: number;
  previousOhms: number | null;
  verdict: SiteVerdict;
};

export type ImpedanceSummary = {
  measuredAt: string;
  frequencyHz: number;
  /** Only the box's channels that were measured, in channel order. */
  sites: SiteJudgement[];
  counts: Record<SiteVerdict, number>;
  /** The channels the box records that this measurement has no value for. */
  missing: string[];
};

/** Judge one animal's latest measurement for the channels its box records now. */
export function summarizeImpedance(
  comparison: ImpedanceComparison,
  channels: readonly string[],
  flags: ImpedanceFlags,
): ImpedanceSummary {
  const { current, previous } = comparison;
  const counts: Record<SiteVerdict, number> = { open: 0, short: 0, changed: 0, ok: 0 };
  const sites: SiteJudgement[] = [];
  const missing: string[] = [];
  for (const channel of channels) {
    const site = current.sites[channel];
    if (!site) {
      missing.push(channel);
      continue;
    }
    const previousOhms = previous?.sites[channel]?.ohms ?? null;
    const verdict = siteVerdict(site.ohms, previousOhms, flags);
    counts[verdict] += 1;
    sites.push({ channel, ohms: site.ohms, previousOhms, verdict });
  }
  return { measuredAt: current.measuredAt, frequencyHz: current.frequencyHz, sites, counts, missing };
}

const VERDICT_TONE: Record<SiteVerdict, "error" | "warning" | "ok"> = {
  open: "error",
  short: "error",
  changed: "warning",
  ok: "ok",
};

/** Each judged site as the probe map marks it: a tone and a hover label. */
export function siteMarks(
  summary: ImpedanceSummary,
): Record<string, { tone: "error" | "warning" | "ok"; label: string }> {
  return Object.fromEntries(
    summary.sites.map((site) => [
      site.channel,
      {
        tone: VERDICT_TONE[site.verdict],
        label: `${formatOhms(site.ohms)}${site.verdict === "ok" ? "" : ` · ${site.verdict}`}${
          site.previousOhms !== null ? ` (was ${formatOhms(site.previousOhms)})` : ""
        }`,
      },
    ]),
  );
}

/** `980 Ω`, `450 kΩ`, `1.2 MΩ`: three significant figures at most. */
export function formatOhms(ohms: number): string {
  if (!Number.isFinite(ohms)) return "–";
  const [scale, unit] = ohms >= 1e6 ? [1e6, "MΩ"] : ohms >= 1e3 ? [1e3, "kΩ"] : [1, "Ω"];
  const value = ohms / scale;
  const text = value >= 100 ? value.toFixed(0) : value >= 10 ? value.toFixed(1) : value.toFixed(2);
  // Trailing zeros only after a decimal point: "1.20" → "1.2", never "980" → "98".
  return `${text.includes(".") ? text.replace(/\.?0+$/, "") : text} ${unit}`;
}

/** "today", "yesterday", "3 days ago": how long ago, against `now`. */
export function measuredAgo(measuredAt: string, now: Date): string {
  const then = new Date(measuredAt);
  if (Number.isNaN(then.getTime())) return "";
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((day(now) - day(then)) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

function finite(value: unknown, lo: number, hi: number, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value >= lo && value <= hi ? value : fallback;
}

/** Heals per key, as every recording default does; a short bound at or above the open one is refused. */
export function normalizeImpedanceFlags(raw: unknown): ImpedanceFlags {
  const r = typeof raw === "object" && raw !== null && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const d = DEFAULT_IMPEDANCE_FLAGS;
  const openOhms = finite(r["openOhms"], 1e4, 1e9, d.openOhms);
  let shortOhms = finite(r["shortOhms"], 1, 1e8, d.shortOhms);
  if (shortOhms >= openOhms) shortOhms = Math.min(d.shortOhms, openOhms / 10);
  return { openOhms, shortOhms, changeFactor: finite(r["changeFactor"], 1.1, 100, d.changeFactor) };
}

export type { ImpedanceComparison, ImpedanceMeasurement };
