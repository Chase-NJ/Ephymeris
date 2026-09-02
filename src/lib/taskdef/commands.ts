import { CMD } from "@/lib/ws/protocol";
import type { SidecarClient } from "@/lib/ws/client";

import type { TaskDefinition } from "./types";

/**
 * The `tasks.*` and `rig.strobes` calls.
 *
 * `preview` and `save` take the whole definition rather than a patch, for the
 * reason `hardware.preview` does: the checks that matter run over the document
 * as a whole — a reward line serving the other well, two trial types sharing an
 * onset code — and a patch would make the sidecar reconstruct the thing it was
 * about to check.
 *
 * NOTHING HERE FLASHES. Saving generates a sketch folder that discovery then
 * finds, so `port.flash` takes it by path like any other sketch. That is what
 * keeps the session flow free of a special case for a profile-backed run.
 */

export async function listTasks(client: SidecarClient) {
  return client.call(CMD.TASKS_LIST, {});
}

export async function getTask(client: SidecarClient, taskId: string) {
  return client.call(CMD.TASKS_GET, { taskId });
}

export async function previewTask(client: SidecarClient, definition: TaskDefinition) {
  return client.call(CMD.TASKS_PREVIEW, { definition });
}

export async function saveTask(client: SidecarClient, definition: TaskDefinition) {
  return client.call(CMD.TASKS_SAVE, { definition });
}

export async function deleteTask(client: SidecarClient, taskId: string) {
  return client.call(CMD.TASKS_DELETE, { taskId });
}

export async function getStrobes(client: SidecarClient) {
  return client.call(CMD.RIG_STROBES, {});
}

/**
 * A task id from a name — lower snake case, which is what the sidecar accepts.
 *
 * Derived rather than asked for: the id names a file and never appears on
 * screen after creation, so a second field for it would be a question with no
 * consequence. A collision is the caller's to resolve, since only it knows
 * what is already stored.
 */
export function idFromName(name: string, taken: readonly string[] = []): string {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^([^a-z])/, "t$1")
      .slice(0, 40) || "task";
  if (!taken.includes(base)) return base;
  for (let n = 2; n < 100; n++) {
    const candidate = `${base}_${n}`;
    if (!taken.includes(candidate)) return candidate;
  }
  return `${base}_${Date.now().toString(36).slice(-4)}`;
}
