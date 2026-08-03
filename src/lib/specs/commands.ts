import type { SidecarClient } from "@/lib/ws/client";
import { CMD } from "@/lib/ws/protocol";
import type {
  SpecArtifact,
  SpecCapabilities,
  SpecCompileResult,
  SpecDocument,
  SpecEntry,
  SpecListingDiff,
  SpecSchema,
} from "./types";

export async function listSpecs(client: SidecarClient): Promise<SpecEntry[]> {
  const result = await client.call(CMD.SPECS_LIST, {});
  return result.specs;
}

export async function getSpec(
  client: SidecarClient,
  specId: string,
): Promise<{ specId: string; origin: string; text: string; raw: SpecDocument | null }> {
  return (await client.call(CMD.SPECS_GET, { specId })) as {
    specId: string;
    origin: string;
    text: string;
    raw: SpecDocument | null;
  };
}

export async function getSpecSchema(client: SidecarClient): Promise<SpecSchema> {
  return (await client.call(CMD.SPECS_SCHEMA, {})) as unknown as SpecSchema;
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

export async function acknowledgeUpstream(
  client: SidecarClient,
  specId: string,
): Promise<{ entry: SpecEntry }> {
  return await client.call(CMD.SPECS_ACKNOWLEDGE_UPSTREAM, { specId });
}

export async function diffSpec(
  client: SidecarClient,
  specId: string,
  text: string,
  against: { baseline?: "shipped" | "saved"; againstSpecId?: string },
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
