/**
 * An animal's implant: the form's logic — `DATA.md#implants`.
 *
 * The sidecar validates and stores an implant (`cohorts/implants.py`); this is
 * the same reading of it for the editor, so a problem shows beside the field
 * before Save is pressed. Pure on purpose: `ImplantEditor.tsx` only renders.
 *
 * A **target** is a group of the device's channels at one place in the brain
 * (`GLOSSARY.md#target`), and its channels are numbered on the device, never
 * by RHX's native name.
 */

import type { Implant, ImplantLowering, ImplantTarget } from "@/lib/ws/protocol";

export type { Implant, ImplantLowering, ImplantTarget };

export const HEMISPHERES = ["left", "right", "midline"] as const;

/** The highest channel number a device can have: RHX's largest controller. */
export const MAX_CHANNEL = 1023;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A date the sidecar will take: `YYYY-MM-DD`, and a real day. */
export function isDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/**
 * A target's channels: a range (`0-15`), a list (`0,2,4`) or both. The
 * channels in the order written, or a sentence saying why not.
 */
export function parseChannels(spec: string): number[] | string {
  const hint = "a range such as 0-15 or a list such as 0,2,4";
  if (spec.trim() === "") return `Channels are ${hint}.`;
  const out: number[] = [];
  for (const part of spec.split(",")) {
    const match = /^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$/.exec(part);
    if (!match) return `“${spec.trim()}” is not ${hint}.`;
    const low = Number(match[1]);
    const high = match[2] === undefined ? low : Number(match[2]);
    if (high < low || high > MAX_CHANNEL) return `“${part.trim()}” does not name a range of the device's channels.`;
    for (let channel = low; channel <= high; channel += 1) out.push(channel);
  }
  if (new Set(out).size !== out.length) return `“${spec.trim()}” names a channel twice.`;
  return out;
}

/** A new target with nothing but its channels and hemisphere chosen. */
export function blankTarget(channels = ""): ImplantTarget {
  return { name: "", region: "", hemisphere: "left", apMm: 0, mlMm: 0, dvMm: 0, channels };
}

/** A new implant: one empty target, no lowerings. */
export function blankImplant(surgeryDate: string): Implant {
  return { device: "", surgeryDate, probeMapPath: null, targets: [blankTarget()], lowerings: [] };
}

/**
 * The lab's custom 32-channel electrode: two bundles of 16, in the holes the
 * EIB numbers 0 to 15 and 16 to 31. Only the names, regions and coordinates
 * are left to type.
 */
export function twoBundleImplant(surgeryDate: string): Implant {
  return {
    device: "custom 32-channel electrode",
    surgeryDate,
    probeMapPath: null,
    targets: [blankTarget("0-15"), blankTarget("16-31")],
    lowerings: [],
  };
}

/**
 * The first thing wrong with an implant, in words, or null when the sidecar
 * will take it. The same rules, in the same order, as `parse_implant`.
 */
export function implantProblem(implant: Implant): string | null {
  if (implant.device.trim() === "") return "Give the device a name.";
  if (!isDate(implant.surgeryDate)) return "The surgery date is a date such as 2026-11-30.";
  if (implant.targets.length === 0) return "An implant needs at least one target.";
  const names = new Set<string>();
  const claimed = new Map<number, string>();
  for (const target of implant.targets) {
    const name = target.name.trim();
    if (name === "") return "Every target needs a name.";
    if (names.has(name.toLowerCase())) return `Two targets are called “${name}”.`;
    names.add(name.toLowerCase());
    for (const [value, label] of [
      [target.apMm, "AP"],
      [target.mlMm, "ML"],
      [target.dvMm, "DV"],
    ] as const) {
      if (!Number.isFinite(value)) return `${name}: ${label} is a number of millimetres.`;
    }
    const channels = parseChannels(target.channels);
    if (typeof channels === "string") return `${name}: ${channels}`;
    for (const channel of channels) {
      const other = claimed.get(channel);
      if (other !== undefined) return `${other} and ${name} both claim channel ${channel}.`;
      claimed.set(channel, name);
    }
  }
  for (const lowering of implant.lowerings) {
    if (!isDate(lowering.date)) return "A lowering's date is a date such as 2026-12-14.";
    if (lowering.date < implant.surgeryDate) {
      return `A lowering on ${lowering.date} is before the surgery (${implant.surgeryDate}).`;
    }
    if (!Number.isFinite(lowering.mm) || lowering.mm === 0) {
      return "A lowering's distance is a number of millimetres, and not 0.";
    }
  }
  return null;
}

/**
 * A target's depth on a date, and the date that depth was set: its DV at
 * surgery plus every lowering on or before the date. One drive carries the
 * whole electrode, so a lowering moves every target.
 */
export function depthOn(implant: Implant, target: ImplantTarget, on: string): { dvMm: number; setOn: string } {
  const past = implant.lowerings.filter((l) => isDate(l.date) && l.date <= on);
  const total = past.reduce((sum, l) => sum + (Number.isFinite(l.mm) ? l.mm : 0), target.dvMm);
  const setOn = past.reduce((latest, l) => (l.date > latest ? l.date : latest), implant.surgeryDate);
  return { dvMm: Math.round(total * 1e6) / 1e6, setOn };
}

/** The lowerings in date order, as the sidecar stores them. */
export function sortedLowerings(lowerings: readonly ImplantLowering[]): ImplantLowering[] {
  return [...lowerings].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

/** The roster row's one line for an implant: its device and its targets. */
export function summarizeImplant(implant: Implant | null | undefined): string {
  if (!implant) return "No implant";
  const targets = implant.targets.map((t) => t.name.trim()).filter((name) => name !== "");
  const device = implant.device.trim() || "Implant";
  return targets.length > 0 ? `${device} · ${targets.join(", ")}` : device;
}

/** What Save posts: text trimmed, lowerings in date order. */
export function cleanImplant(implant: Implant): Implant {
  const probeMap = implant.probeMapPath?.trim() ?? "";
  return {
    device: implant.device.trim(),
    surgeryDate: implant.surgeryDate,
    probeMapPath: probeMap === "" ? null : probeMap,
    targets: implant.targets.map((t) => ({
      ...t,
      name: t.name.trim(),
      region: t.region.trim(),
      channels: t.channels.trim(),
    })),
    lowerings: sortedLowerings(implant.lowerings),
  };
}
