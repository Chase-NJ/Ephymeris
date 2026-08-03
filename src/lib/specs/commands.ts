import type { SidecarClient } from "@/lib/ws/client";
import { CMD } from "@/lib/ws/protocol";
import type {
  SpecCapabilities,
  SpecCompileResult,
  SpecDocument,
  SpecEntry,
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
