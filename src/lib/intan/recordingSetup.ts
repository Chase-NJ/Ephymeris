/**
 * The Record step's rules (`RECORDING.md#record-step`), pure so they can be
 * tested: which rows the form holds for the mapped boxes, whether the setup is
 * ready, and the `intan.configure` it sends. `SessionRecording` gathers the
 * facts and renders the answers.
 */

import type { ProbeMap } from "./types";
import type { RecordingDefaults } from "./defaults";

/** A box's row in the form. `record: false` runs the box behavior-only. */
export interface BoxRow {
  box: number;
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
  animalName: string;
}

/** A new row for a box, from what the last Record step remembered for it. */
function seedRow(box: MappedBox, defaults: RecordingDefaults): BoxRow {
  const memory = defaults.boxes[String(box.box)];
  return {
    box: box.box,
    animalName: box.animalName,
    record: memory?.record ?? true,
    port: memory?.port ?? "",
    firstChannel: memory?.firstChannel ?? 0,
    lastChannel: memory?.lastChannel ?? -1,
    probeMapPath: memory?.probeMapPath ?? null,
    probeMap: null,
    probeError: null,
  };
}

/**
 * The form's rows for the boxes mapped now, given the rows it already holds (a
 * restored draft, or what was typed).
 */
export function reconcileRows(
  boxes: readonly MappedBox[],
  defaults: RecordingDefaults,
  draftRows: BoxRow[],
): BoxRow[] {
  if (boxes.length === 0) return draftRows;
  if (draftRows.length > 0) return draftRows;
  return boxes.map((b) => seedRow(b, defaults));
}
