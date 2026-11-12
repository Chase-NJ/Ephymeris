import type {
  ChannelSetConflict,
  ChannelSetImportPlan,
  ChannelSetNewChannel,
} from "@/lib/ws/protocol";

/**
 * The channel-set import dialog's reading of the sidecar's plan
 * (`TASKS.md#adding-a-channel-lab-wide`).
 *
 * NOTHING HERE JUDGES A PIN. The free pins, the conflicts and whether a pick
 * holds all come from `hardware.importChannelSet`'s plan, re-planned with the
 * picks on every change; these functions only sort what it said.
 */

/** The operator's picks, channel → pin; a channel with no pick is absent. */
export type PinPicks = Readonly<Record<string, number>>;

/**
 * The `pins` argument for these picks: only channels the plan lists as new,
 * so a pick left over from another file is never sent as a `pin` conflict.
 */
export function pinsToSend(plan: ChannelSetImportPlan | null, picks: PinPicks): Record<string, number> {
  const out: Record<string, number> = {};
  for (const { channel } of plan?.newChannels ?? []) {
    const pin = picks[channel];
    if (pin !== undefined) out[channel] = pin;
  }
  return out;
}

/** `picks` with `channel` set to `pin`, or cleared when `pin` is null. */
export function withPick(picks: PinPicks, channel: string, pin: number | null): PinPicks {
  const { [channel]: _dropped, ...rest } = picks;
  return pin === null ? rest : { ...rest, [channel]: pin };
}

/**
 * The conflicts the dialog lists as refusals: every one except a new
 * channel's `not_here`, which its own row asks to be pinned.
 */
export function refusals(plan: ChannelSetImportPlan): ChannelSetConflict[] {
  const rows = new Set(plan.newChannels.map((c) => c.channel));
  return plan.conflicts.filter((c) => !(c.kind === "not_here" && c.channel && rows.has(c.channel)));
}

/** New channels the plan still has no pin for. */
export function unpinned(plan: ChannelSetImportPlan): ChannelSetNewChannel[] {
  return plan.newChannels.filter((c) => c.pin === null);
}

/**
 * Whether Import can be pressed: the sidecar's plan for the current picks has
 * no conflict, pins every new channel, and changes something. `pending` (a
 * re-plan in flight) holds it, so Import never applies picks the shown plan
 * has not judged.
 */
export function canImport(plan: ChannelSetImportPlan | null, pending: boolean): boolean {
  return (
    !!plan &&
    !pending &&
    plan.conflicts.length === 0 &&
    unpinned(plan).length === 0 &&
    !plan.identical
  );
}
