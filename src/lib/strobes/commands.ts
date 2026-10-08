import { CMD } from "@/lib/ws/protocol";
import type { SidecarClient } from "@/lib/ws/client";

/**
 * The `strobes.*` calls — `TASKS.md#strobe-vocabulary`.
 *
 * EVERY RULE LIVES IN THE SIDECAR. Whether a code may be retired or removed is
 * reported by `strobes.usage` (`retireBlocker`, `removeBlocker`) and enforced
 * again by the command itself, so this page never predicts a refusal: it shows
 * the sidecar's reason, and a refusal it did not foresee arrives as the
 * command's error.
 */

/**
 * An archive scan reads every recorded session this machine can reach. The
 * cache makes a warm one quick; a cold one over a network share is minutes,
 * and cutting the promise early would report a failure the sidecar did not have.
 */
const SCAN_TIMEOUT_MS = 600_000;

export function getVocabulary(client: SidecarClient) {
  return client.call(CMD.STROBES_GET, {});
}

export function strobeUsage(client: SidecarClient, name: string, scan = false) {
  return client.call(
    CMD.STROBES_USAGE,
    { name, scan },
    scan ? { timeoutMs: SCAN_TIMEOUT_MS } : {},
  );
}

export function addStrobe(
  client: SidecarClient,
  args: { name: string; code: number; rationale: string; emittedOn?: string },
) {
  return client.call(CMD.STROBES_ADD, args);
}

export function editStrobe(
  client: SidecarClient,
  args: { name: string; rationale: string; emittedOn?: string },
) {
  return client.call(CMD.STROBES_EDIT, args);
}

export function retireStrobe(client: SidecarClient, name: string, confirm: boolean) {
  return client.call(CMD.STROBES_RETIRE, { name, confirm });
}

export function reinstateStrobe(client: SidecarClient, name: string) {
  return client.call(CMD.STROBES_REINSTATE, { name });
}

export function removeStrobe(client: SidecarClient, name: string, confirm: boolean) {
  return client.call(CMD.STROBES_REMOVE, { name, confirm }, { timeoutMs: SCAN_TIMEOUT_MS });
}

export function exportVocabulary(client: SidecarClient) {
  return client.call(CMD.STROBES_EXPORT, {});
}

export function importVocabulary(client: SidecarClient, document: unknown, apply: boolean) {
  return client.call(CMD.STROBES_IMPORT, { document, apply });
}
