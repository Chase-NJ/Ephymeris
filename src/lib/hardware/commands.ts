import { CMD } from "@/lib/ws/protocol";
import type { SidecarPort } from "@/lib/ws/port";

import type { RigDocument } from "./types";

/**
 * The `hardware.*` calls.
 *
 * `preview` and `save` take the whole document rather than a patch: the checks
 * that matter run over the document as a whole — two channels sharing a pin,
 * two ports claiming one strobe slot — and a patch would make the sidecar
 * reconstruct the thing it was about to check.
 */

export async function getRig(client: SidecarPort) {
  return client.call(CMD.HARDWARE_GET, {});
}

/** `confirmedPins` is the operator's own act (`status.needsPinConfirmation`),
 *  carried with the request; the sidecar enforces it. */
export async function previewRig(client: SidecarPort, document: RigDocument, confirmedPins = false) {
  return client.call(CMD.HARDWARE_PREVIEW, { document, confirmedPins });
}

export async function saveRig(
  client: SidecarPort,
  document: RigDocument,
  confirm: boolean,
  confirmedPins = false,
) {
  return client.call(CMD.HARDWARE_SAVE, { document, confirm, confirmedPins });
}

export async function resetRig(client: SidecarPort) {
  return client.call(CMD.HARDWARE_RESET, {});
}

/** The channel set and vocabulary as they travel to the other lab machine
 *  (`TASKS.md#moving-the-channel-set-between-machines`). */
export async function exportChannelSet(client: SidecarPort) {
  return client.call(CMD.HARDWARE_EXPORT_CHANNEL_SET, {});
}

/** Plan (`apply: false`) or apply another machine's export. The sidecar decides
 *  every conflict; `confirm` passes a plan's `breaks`, as for `saveRig`. */
export async function importChannelSet(
  client: SidecarPort,
  document: unknown,
  apply: boolean,
  confirm = false,
) {
  return client.call(CMD.HARDWARE_IMPORT_CHANNEL_SET, { document, apply, confirm });
}

/**
 * Queue a Debug Mode flash of one sketch onto these boxes, one at a time
 * (`ARCHITECTURE.md#the-flash-queue`). Returns once queued; `flash.queue`
 * reports the rest. With `baud`, each box ends in a console opened at it.
 */
export async function enqueueFlash(
  client: SidecarPort,
  boxes: readonly number[],
  sketchPath: string,
  baud?: number,
) {
  return client.call(CMD.FLASH_ENQUEUE, {
    boxes: [...boxes],
    sketchPath,
    ...(baud !== undefined ? { baud } : {}),
  });
}

/** Drop queued session and Debug flashes; one under way finishes. */
export async function cancelFlashes(client: SidecarPort, boxes?: readonly number[]) {
  return client.call(CMD.FLASH_CANCEL, boxes ? { boxes: [...boxes] } : {});
}
