/**
 * The shipped default strobe vocabulary, for tests — read from the one file
 * that defines it, never transcribed. A hand-written map here once carried
 * LIGHTS_ON as 220 (it is 222) and passed only because everything under test
 * looks codes up by name. `TASKS.md#strobe-vocabulary`.
 */

import seed from "../../../../sidecar/ephymeris_sidecar/rig/schema/strobe_vocab.default.json";

type Entry = { code: number };

const live = seed.codes as Record<string, Entry>;
const retired = seed.retired as unknown as Record<string, Entry | string[]>;

/** `code -> name`, as a profile's `strobes` map carries it. */
export const STROBES: Record<string, string> = Object.fromEntries([
  ...Object.entries(live).map(([name, e]) => [String(e.code), name]),
  ...Object.entries(retired)
    .filter((kv): kv is [string, Entry] => !kv[0].startsWith("_"))
    .map(([name, e]) => [String(e.code), name]),
]);

/** A live code's number. Throws on a name the vocabulary does not hold. */
export function code(name: string): number {
  const entry = live[name];
  if (!entry) throw new Error(`${name} is not in the default strobe vocabulary`);
  return entry.code;
}

/** Names → the string codes a strobe tail carries. */
export const tail = (...names: string[]): string[] => names.map((n) => String(code(n)));
