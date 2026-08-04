import type { SidecarClient } from "@/lib/ws/client";
import { CMD } from "@/lib/ws/protocol";
import type { BoardCapabilities, UploadResult, UtilityStatus } from "@/lib/ws/protocol";
import type {
  ParadigmSummary,
  SpecArtifact,
  SpecCapabilities,
  SpecCompileResult,
  SpecDocument,
  SpecEntry,
  SpecListingDiff,
  SpecOrigin,
  SpecSchema,
} from "./types";

export async function listSpecs(client: SidecarClient): Promise<SpecEntry[]> {
  const result = await client.call(CMD.SPECS_LIST, {});
  return result.specs;
}

export async function getSpec(
  client: SidecarClient,
  specId: string,
): Promise<{ specId: string; origin: SpecOrigin; text: string; raw: SpecDocument | null }> {
  const reply = await client.call(CMD.SPECS_GET, { specId });
  // `raw` is `any` on the wire — the parsed document has no fixed shape, and
  // the compiler is the authority on what a legal one looks like.
  return { ...reply, raw: (reply.raw ?? null) as SpecDocument | null };
}

export async function getSpecSchema(client: SidecarClient): Promise<SpecSchema> {
  return await client.call(CMD.SPECS_SCHEMA, {});
}

export async function compileSpec(
  client: SidecarClient,
  text: string,
  specId?: string,
): Promise<SpecCompileResult> {
  return await client.call(CMD.SPECS_COMPILE, specId ? { text, specId } : { text });
}

export async function getCapabilities(
  client: SidecarClient,
  topology: Record<string, unknown>,
): Promise<SpecCapabilities> {
  return await client.call(CMD.SPECS_CAPABILITIES, { topology });
}

/** Every shape a new task can start from. Static for the life of the process. */
export async function getParadigms(client: SidecarClient): Promise<ParadigmSummary[]> {
  const reply = await client.call(CMD.SPECS_PARADIGMS, {});
  return reply.paradigms;
}

/**
 * A first draft for a paradigm, and the compile of it.
 *
 * Writes nothing — creating the task is still `saveSpec`, so rename-and-save
 * keeps its single definition and a wizard abandoned halfway leaves no orphan.
 * The compile rides along so the first render already has a graph.
 */
export async function getSkeleton(
  client: SidecarClient,
  paradigmId: string,
  specId: string,
  answers: Record<string, unknown>,
  meta?: { label?: string; description?: string },
): Promise<{ text: string; result: SpecCompileResult }> {
  return await client.call(CMD.SPECS_SKELETON, {
    paradigmId,
    specId,
    answers,
    ...(meta?.label ? { label: meta.label } : {}),
    ...(meta?.description ? { description: meta.description } : {}),
  });
}

export async function saveSpec(
  client: SidecarClient,
  specId: string,
  text: string,
): Promise<{ entry: SpecEntry; result: SpecCompileResult }> {
  return await client.call(CMD.SPECS_SAVE, { specId, text });
}

export async function deleteSpec(
  client: SidecarClient,
  specId: string,
): Promise<{ entry: SpecEntry | null }> {
  return await client.call(CMD.SPECS_DELETE, { specId });
}

export async function diffSpec(
  client: SidecarClient,
  specId: string,
  text: string,
  against: { againstSpecId?: string },
): Promise<SpecListingDiff> {
  return await client.call(CMD.SPECS_DIFF, { specId, text, ...against });
}

export async function exportSpec(
  client: SidecarClient,
  specId: string,
  text: string,
  artifacts: string[],
): Promise<{ artifacts: SpecArtifact[] }> {
  return await client.call(CMD.SPECS_EXPORT, { specId, text, artifacts });
}

/* --- Bench boxes ---------------------------------------------------------
 *
 * The hardware half of the spec surface. Same module as the rest because it
 * answers the same question — what does this rig do with a spec — and one
 * wrapper module per domain is how every other domain here is arranged.
 */

/**
 * Read a board's CAP banner and stop. Costs one DTR reset (opening the port
 * *is* the reset) and changes nothing on the board.
 *
 * `baud` is deliberately not passed: absent means the sidecar tries 115200
 * then 9600 and caches the answer per hardware id. `settings.defaultBaud` is
 * the *console* default and would be the wrong number here.
 */
export async function boardCapabilities(
  client: SidecarClient,
  box: number,
): Promise<BoardCapabilities> {
  return await client.call(CMD.BOARD_CAPABILITIES, { box });
}

/** Compile → detect → CAP check → chunked transfer → verify. The table is
 * compiled server-side from this text; a client-supplied table is never
 * trusted, so the compiler's structural gate holds on the hardware path too. */
export async function uploadTable(
  client: SidecarClient,
  box: number,
  specId: string,
  text: string,
): Promise<UploadResult> {
  return await client.call(CMD.BOARD_UPLOAD_TABLE, { box, specId, text });
}

/** Suspend the utility baseline's restores while a bench surface is mounted.
 * Without it an upload ends with the port falling IDLE and the baseline
 * reflashing over the interpreter — the table dies and nothing errors. */
export async function setBenchHold(
  client: SidecarClient,
  held: boolean,
): Promise<UtilityStatus> {
  return await client.call(CMD.UTILITY_BENCH_HOLD, { held });
}
