import type { RigDocument } from "@/lib/hardware/types";
import type { StrobeVocabulary } from "@/lib/ws/protocol";

import { channelLabel, type TrialTypeDef } from "./types";

/**
 * Odor lines and the onset codes they announce (`TASKS.md#onset-codes`).
 *
 * THE PAIRING IS THE RIG'S, DECLARED, NEVER DERIVED. Each emitter names its
 * onset code in the wiring (`onset_strobe`), the way a response port names its
 * slot; the task editor reads that declaration and writes it into the row. The
 * channel's name and its position are never consulted — the onsets run 101-109
 * and then 114-116, and the emitter pins are not in line order.
 */

/** One picker row — structurally `Dropdown`'s option, kept here so `lib/` does
 *  not reach into `components/`. */
export interface PickOption {
  value: string;
  label: string;
  detail?: string;
  disabled?: boolean;
}

/**
 * The shape of a stimulus onset code (`ODOR_3_ON`). A SHAPE CHECK ONLY — it
 * filters a picker and never yields a number. Mirrors `ONSET_NAME` in
 * `sidecar/ephymeris_sidecar/rig/registry.py`, which RIG106 checks with.
 */
export const ONSET_NAME = /_\d+_ON$/;

/** The onset code this rig declares for an odor line, or null. */
export function declaredOnset(rig: RigDocument | null, line: string): string | null {
  const channel = rig?.channels?.[line];
  if (!channel || channel.kind !== "emitter") return null;
  return channel.onset_strobe?.trim() || null;
}

/** A code's number, read from the vocabulary — never computed. */
export function codeNumber(vocabulary: StrobeVocabulary | null, name: string): number | null {
  return vocabulary?.codes.find((c) => c.name === name)?.code ?? null;
}

/**
 * The odor lines a trial row may pick, in declaration order.
 *
 * A line another row already presents is listed but disabled: one line
 * declares one code, and two conditions on one code are TSK105. Listed rather
 * than hidden, with the row that holds it, so "where did line 3 go" has an
 * answer on screen.
 */
export function lineOptions(
  rig: RigDocument | null,
  vocabulary: StrobeVocabulary | null,
  trials: readonly TrialTypeDef[],
  row: number,
): PickOption[] {
  const takenBy = new Map<string, number>();
  trials.forEach((t, i) => {
    if (i !== row && t.odorChannel && !takenBy.has(t.odorChannel)) takenBy.set(t.odorChannel, i);
  });
  return Object.entries(rig?.channels ?? {})
    .filter(([, c]) => c.kind === "emitter")
    .map(([name]) => {
      const onset = declaredOnset(rig, name);
      const other = takenBy.get(name);
      const number = onset ? codeNumber(vocabulary, onset) : null;
      return {
        value: name,
        label: channelLabel(rig, name),
        detail:
          other !== undefined
            ? `in row ${other + 1}`
            : onset
              ? `${onset}${number !== null ? ` · ${number}` : ""}`
              : "no onset",
        disabled: other !== undefined,
      };
    });
}

/**
 * The onset codes an emitter may declare on the Rig tab: live, onset-shaped,
 * and not already declared by another line (listed, disabled, with its owner).
 */
export function onsetOptions(
  rig: RigDocument | null,
  vocabulary: StrobeVocabulary | null,
  channel: string,
): PickOption[] {
  const owner = new Map<string, string>();
  for (const [name, c] of Object.entries(rig?.channels ?? {})) {
    if (name !== channel && c.kind === "emitter" && c.onset_strobe) owner.set(c.onset_strobe, name);
  }
  return (vocabulary?.codes ?? [])
    .filter((c) => ONSET_NAME.test(c.name))
    .map((c) => {
      const other = owner.get(c.name);
      return {
        value: c.name,
        label: c.name,
        detail: other ? `on ${channelLabel(rig, other)}` : String(c.code),
        disabled: other !== undefined,
      };
    });
}

/**
 * A catalogue field whose value the generator reads off a trial ROW, never out
 * of `params` — `pool_weight_N` and `reward_time_N`. An edit to one anywhere
 * but the row is stored and ignored, so the editor offers them on the row only
 * and never writes them into `params`.
 */
export function isRowOwnedField(metadataKey: string): boolean {
  return /^(pool_weight|reward_time)_\d+$/.test(metadataKey);
}
