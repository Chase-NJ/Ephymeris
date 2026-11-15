import type { RigDocument, RigReservedPin } from "./types";

/**
 * Which pins the Wiring editor offers a channel.
 *
 * NOT A BOARD FACT OF ITS OWN. The pins no channel may take (the Mega's USB
 * serial pins, `rig/board.py`) come from the sidecar as `reservedPins`, the
 * same table RIG102 refuses them by, so the editor cannot offer a pin a
 * preview would then flag (`TASKS.md#wiring-rules`).
 */

/** True when `pin` is one the board reserves. */
export function isReserved(pin: number, reserved: readonly RigReservedPin[]): boolean {
  return reserved.some((r) => r.pin === pin);
}

/**
 * The lowest pin of `doc.pin_range` that no channel is on and the board does
 * not reserve, or null when every one is taken.
 */
export function lowestFreePin(doc: RigDocument, reserved: readonly RigReservedPin[]): number | null {
  const used = new Set(Object.values(doc.pins ?? {}).map((p) => p.index));
  const min = doc.pin_range?.min ?? 0;
  const max = doc.pin_range?.max ?? 53;
  for (let pin = min; pin <= max; pin += 1) {
    if (!used.has(pin) && !isReserved(pin, reserved)) return pin;
  }
  return null;
}
