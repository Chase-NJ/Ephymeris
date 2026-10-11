import { CMD } from "@/lib/ws/protocol";
import type { SidecarPort } from "@/lib/ws/port";

import type { RigDocument } from "./types";

/**
 * The four `hardware.*` calls.
 *
 * `preview` and `save` take the whole document rather than a patch: the checks
 * that matter run over the document as a whole — two channels sharing a pin,
 * two ports claiming one strobe slot — and a patch would make the sidecar
 * reconstruct the thing it was about to check.
 */

export async function getRig(client: SidecarPort) {
  return client.call(CMD.HARDWARE_GET, {});
}

export async function previewRig(client: SidecarPort, document: RigDocument) {
  return client.call(CMD.HARDWARE_PREVIEW, { document });
}

export async function saveRig(
  client: SidecarPort,
  document: RigDocument,
  confirm: boolean,
) {
  return client.call(CMD.HARDWARE_SAVE, { document, confirm });
}

export async function resetRig(client: SidecarPort) {
  return client.call(CMD.HARDWARE_RESET, {});
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
