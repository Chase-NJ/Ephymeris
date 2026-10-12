/**
 * The Record step's rules (`RECORDING.md#record-step`), pure so they can be
 * tested: which rows the form holds for the mapped boxes, which port each is
 * guessed onto, whether the setup is ready, and the `intan.configure` it
 * sends. `SessionRecording` gathers the facts and renders the answers.
 */

import type { BoxBinding } from "@/lib/ws/protocol";

import type { RecordingConfigDefaults, RecordingDefaults } from "./defaults";
import { channelRange } from "./scopeMath";
import type { IntanStatus, ProbeMap, RecordingBoxConfig, RecordingConfig } from "./types";

/** A box's row in the form. `record: false` runs the box behavior-only. */
export interface BoxRow {
  box: number;
  /** The animal the row was filled in for. */
  animalId: string;
  animalName: string;
  record: boolean;
  port: string;
  firstChannel: number;
  lastChannel: number;
  probeMapPath: string | null;
  probeMap: ProbeMap | null;
  probeError: string | null;
}

/** A mapped box as the sidecar reports it; only what a row needs. */
export interface MappedBox {
  box: number;
  animalId: string;
  animalName: string;
}

// --- the rows -----------------------------------------------------------------

/**
 * A new row for a box: its wiring from what the box remembers, and its probe
 * map from its animal — the one chosen for it this visit (`chosen`, a draft
 * row of the same animal on another box), else the one remembered for it,
 * else none.
 */
function seedRow(box: MappedBox, defaults: RecordingDefaults, chosen: BoxRow | undefined): BoxRow {
  const memory = defaults.boxes[String(box.box)];
  const probe = chosen
    ? { probeMapPath: chosen.probeMapPath, probeMap: chosen.probeMap, probeError: chosen.probeError }
    : { probeMapPath: defaults.probeMaps[box.animalId] ?? null, probeMap: null, probeError: null };
  return {
    box: box.box,
    animalId: box.animalId,
    animalName: box.animalName,
    record: memory?.record ?? true,
    port: memory?.port ?? "",
    firstChannel: memory?.firstChannel ?? 0,
    lastChannel: memory?.lastChannel ?? -1,
    ...probe,
  };
}

/**
 * The form's rows for the boxes mapped now, given the rows it already holds (a
 * restored draft, or what was typed).
 *
 * Keyed to the CURRENT boxes, never to the rows (`ARCHITECTURE.md#leaving-set-up`):
 * - the same animal on the same box keeps what was typed for it (under its
 *   current name, should it have been renamed);
 * - a box no longer mapped is dropped;
 * - a newly mapped box, or one whose animal changed, gets a fresh row
 *   (`seedRow`): the box's wiring, and its animal's probe map.
 *
 * The same array comes back when nothing changed, so a repeated answer from
 * the sidecar neither re-renders nor rewrites the draft. No boxes (not loaded
 * yet, or the rig not held) keeps the rows as they are.
 */
export function reconcileRows(
  boxes: readonly MappedBox[],
  defaults: RecordingDefaults,
  draftRows: BoxRow[],
): BoxRow[] {
  if (boxes.length === 0) return draftRows;
  const byBox = new Map(draftRows.map((r) => [r.box, r]));
  const byAnimal = new Map(draftRows.map((r) => [r.animalId, r]));
  const next = boxes.map((b) => {
    const kept = byBox.get(b.box);
    if (!kept || kept.animalId !== b.animalId) return seedRow(b, defaults, byAnimal.get(b.animalId));
    return kept.animalName === b.animalName ? kept : { ...kept, animalName: b.animalName };
  });
  const unchanged = next.length === draftRows.length && next.every((r, i) => r === draftRows[i]);
  return unchanged ? draftRows : next;
}

// --- ports ------------------------------------------------------------------

/** The headstage ports RHX reports channels on, in letter order. */
export function presentPorts(ports: Readonly<Record<string, number>>): string[] {
  return Object.entries(ports)
    .filter(([, count]) => count > 0)
    .map(([letter]) => letter)
    .sort();
}

/**
 * Each row on a port RHX reports: an unassigned box (or one on a port that is
 * gone) gets the next free port with its whole range, and a range past the
 * port's channel count is clipped to it. A guess the operator can see and
 * change, which beats a blank they must fill for every box every session.
 *
 * The same array comes back when nothing moved, and the rows untouched while
 * RHX reports no port.
 */
export function assignPorts(rows: BoxRow[], ports: Readonly<Record<string, number>>): BoxRow[] {
  const present = presentPorts(ports);
  if (present.length === 0) return rows;
  const taken = new Set(rows.filter((r) => r.port).map((r) => r.port));
  let changed = false;
  const next = rows.map((row) => {
    let { port, lastChannel } = row;
    if (!port || !present.includes(port)) {
      port = present.find((p) => !taken.has(p)) ?? present[0] ?? "";
      taken.add(port);
      lastChannel = -1;
    }
    const count = ports[port] ?? 0;
    if (lastChannel < 0 || lastChannel >= count) lastChannel = Math.max(0, count - 1);
    if (port === row.port && lastChannel === row.lastChannel) return row;
    changed = true;
    return { ...row, port, lastChannel, firstChannel: Math.min(row.firstChannel, lastChannel) };
  });
  return changed ? next : rows;
}

// --- where it saves -----------------------------------------------------------

/**
 * Where RHX saves this session (`RECORDING.md#record-step`): `<session>/ephys`,
 * or the session's folder name under a chosen root. "" until the session's
 * folder is known.
 */
export function saveDirectory(sessionFolder: string | null, saveRoot: string | null): string {
  if (!sessionFolder) return "";
  if (!saveRoot) return `${sessionFolder.replace(/[\\/]+$/, "")}/ephys`;
  const folderName = sessionFolder.split(/[\\/]/).filter(Boolean).pop() ?? "";
  return `${saveRoot.replace(/[\\/]+$/, "")}/${folderName}`;
}

// --- readiness ----------------------------------------------------------------

export interface ReadinessCheck {
  ok: boolean;
  label: string;
  /** Where the failing line is fixed. */
  fix?: { label: string; to: string };
}

export interface RecordingReadiness {
  /** The Readiness tile's lines, in order. */
  checks: ReadinessCheck[];
  /** Two recorded boxes claiming one channel, said as the refusal; null if none. */
  overlap: string | null;
  /** The policy saves at least one signal; the editor stays open until it does. */
  savesSomething: boolean;
  /** The first thing standing in the way, for the Continue button's title. */
  firstProblem: string | null;
  ready: boolean;
  /** The journey bar's one line. */
  hint: string;
}

/** What readiness reads of RHX. */
export type IntanFacts = Pick<
  IntanStatus,
  "connected" | "version" | "controller" | "sampleRate" | "synthetic" | "runMode" | "ports" | "rigHasSync"
>;

/** The first channel two recorded boxes both claim, said as the refusal. */
function channelOverlap(recorded: readonly BoxRow[]): string | null {
  const seen = new Map<string, number>();
  for (const row of recorded) {
    for (const name of channelRange(row.port, row.firstChannel, row.lastChannel)) {
      const other = seen.get(name);
      if (other !== undefined && other !== row.box) return `${name} is claimed by box ${other} and box ${row.box}`;
      seen.set(name, row.box);
    }
  }
  return null;
}

/**
 * Whether the Record step may Continue, and every line that says why not.
 * `rigBoxes` is this machine's box bindings, read for each recorded box's
 * Intan digital input; `directory` is `saveDirectory(...)`.
 */
export function recordingReadiness(
  rows: readonly BoxRow[],
  config: RecordingConfigDefaults | null,
  intan: IntanFacts,
  rigBoxes: readonly Pick<BoxBinding, "box" | "intanDigitalIn">[],
  directory: string,
): RecordingReadiness {
  const ports = presentPorts(intan.ports);
  const recorded = rows.filter((r) => r.record);
  const unbound = recorded.filter((r) => !rigBoxes.find((b) => b.box === r.box)?.intanDigitalIn);
  const overlap = channelOverlap(recorded);
  const savesSomething =
    !!config && (config.saveWideband || config.saveSpikes || config.saveLowpass || config.saveHighpass);
  const recordingNow = intan.runMode === "record" || intan.runMode === "trigger";

  const checks: ReadinessCheck[] = [
    {
      ok: intan.connected,
      label: intan.connected
        ? `RHX ${intan.version ?? ""} · ${intan.controller ?? "controller"} · ${
            intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"
          }${intan.synthetic ? " · synthetic" : ""}`
        : "RHX is not connected — in RHX: Network → Remote TCP Control → Connect (Commands tab)",
      fix: { label: "Open Recording", to: "/recording" },
    },
    {
      ok: intan.connected && !recordingNow,
      label: recordingNow ? "RHX is already recording — stop it in RHX first" : "RHX is not recording",
    },
    {
      ok: intan.connected && ports.length > 0,
      label: ports.length > 0 ? `Headstage on port ${ports.join(", ")}` : "No headstage detected on any port",
    },
    {
      ok: intan.rigHasSync,
      label: intan.rigHasSync
        ? "This rig's wiring has a sync channel"
        : "This rig's wiring has no sync channel, so no box pulses on its events",
      fix: { label: "Open wiring", to: "/config/wiring" },
    },
    {
      ok: recorded.length > 0 && unbound.length === 0,
      label:
        recorded.length === 0
          ? "No box is set to record"
          : unbound.length === 0
            ? "Every recorded box has an Intan digital input"
            : `Box ${unbound.map((r) => r.box).join(", ")} has no Intan digital input bound`,
      fix: { label: "Open Recording", to: "/recording" },
    },
  ];
  const firstProblem =
    checks.find((c) => !c.ok)?.label ?? overlap ?? (!savesSomething ? "Nothing would be saved" : null);
  const ready = checks.every((c) => c.ok) && !overlap && savesSomething && directory !== "";
  const hint = !intan.connected
    ? "Connect Ephymeris to Intan RHX."
    : !ready
      ? "Finish the recording setup."
      : "Ready — continue to Mission Control.";
  return { checks, overlap, savesSomething, firstProblem, ready, hint };
}

// --- what Continue sends --------------------------------------------------------

/**
 * The `config` of `intan.configure`: the policy, where it saves, and each
 * recorded box's port and range. A box running behavior-only is left out, and
 * a probe map is sent only once it has parsed.
 */
export function configurePayload(
  rows: readonly BoxRow[],
  config: RecordingConfigDefaults,
  saveRoot: string | null,
  sessionFolder: string | null,
): RecordingConfig {
  const boxes: RecordingBoxConfig[] = rows
    .filter((r) => r.record)
    .map((r) => ({
      box: r.box,
      port: r.port,
      firstChannel: r.firstChannel,
      lastChannel: r.lastChannel,
      probeMapPath: r.probeMap ? r.probeMapPath : null,
    }));
  return { ...config, saveDirectory: saveDirectory(sessionFolder, saveRoot), boxes };
}

/**
 * What a confirmed Record step leaves as the next one's starting point — not
 * the save directory (it is per session) and not the boxes list (it is per
 * group), but each box's port and range under the box, behavior-only boxes
 * included, and each row's probe map under its animal. `probeMaps` is what was
 * remembered before: an animal not on the form keeps its entry, and one whose
 * row has no probe map forgets it.
 */
export function rememberedDefaults(
  rows: readonly BoxRow[],
  config: RecordingConfigDefaults,
  saveRoot: string | null,
  probeMaps: Readonly<Record<string, string>>,
): RecordingDefaults {
  const nextMaps: Record<string, string> = { ...probeMaps };
  for (const r of rows) {
    if (r.probeMapPath) nextMaps[r.animalId] = r.probeMapPath;
    else delete nextMaps[r.animalId];
  }
  return {
    saveRoot,
    config,
    probeMaps: nextMaps,
    boxes: Object.fromEntries(
      rows.map((r) => [
        String(r.box),
        { record: r.record, port: r.port, firstChannel: r.firstChannel, lastChannel: r.lastChannel },
      ]),
    ),
  };
}
