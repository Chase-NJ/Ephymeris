import { useCallback, useEffect, useRef, useState } from "react";

import { useHardwareStore } from "./context";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { CMD, EVT, SidecarCommandError } from "@/lib/ws/protocol";

/**
 * The Config serial handshake test (settings.md §5).
 *
 * Composed entirely from existing wire primitives — no handshake command
 * exists on the sidecar, deliberately. Opening a passthrough port asserts DTR,
 * which resets the Mega, and the boot output is captured into `port.output`
 * (`dashboard.md` §6.3). So the test is: open, listen, close.
 * `port.reset` is unsuitable: its DTR pulse uses a throwaway unread handle, so
 * its own boot output is unobservable — and it would reset the board twice.
 *
 * Tiers, best to worst:
 *   ready  — the board printed `READY`: it speaks the Ephymeris protocol.
 *   output — the board printed *something*: wiring and port are good; the
 *            sketch just isn't an Ephymeris task (or booted past READY).
 *   silent — the port opened but nothing arrived: wrong baud, or a blank or
 *            mute sketch. A warning, not a failure — the wiring may be fine.
 *   failed — the port never opened (unbound box, missing/busy port).
 */

export type HandshakeTier = "ready" | "output" | "silent" | "failed";

export interface HandshakeState {
  phase: "idle" | "running" | "done";
  tier?: HandshakeTier;
  /** Operator-facing note: error cause, or what was heard. */
  detail?: string;
}

/** Mirrors the sidecar's own READY budget (`SESSION_READY_TIMEOUT_S`). */
const LISTEN_MS = 10_000;

/** The same token the session path awaits (`dashboard.md` §10). */
const READY_RE = /^READY\b/;

const FAILED_DETAIL: Record<string, string> = {
  PORT_NOT_BOUND: "no board is bound to this box",
  PORT_OPEN_FAILED: "the port is missing or busy",
  ILLEGAL_TRANSITION: "the box is busy — flashing, resetting, or in a session",
};

export function useHandshakeTest(): {
  run: (box: number) => Promise<void>;
  stateFor: (box: number) => HandshakeState;
  anyRunning: boolean;
} {
  const { client } = useSidecar();
  const { settings } = useSettings();
  const store = useHardwareStore();
  const [states, setStates] = useState<ReadonlyMap<number, HandshakeState>>(new Map());
  // Unmount must drop pending results but still close in-flight ports — a
  // navigation away mid-test must never leave a port open.
  const cancelled = useRef(false);
  const inFlight = useRef(new Set<number>());

  useEffect(() => {
    cancelled.current = false;
    const flight = inFlight.current;
    return () => {
      cancelled.current = true;
      for (const box of flight) {
        void client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }).catch(() => {});
      }
    };
  }, [client]);

  const set = useCallback((box: number, state: HandshakeState) => {
    if (cancelled.current) return;
    setStates((prev) => {
      const next = new Map(prev);
      next.set(box, state);
      return next;
    });
  }, []);

  const run = useCallback(
    async (box: number) => {
      if (inFlight.current.has(box)) return;

      // The sidecar is the authority on state; this pre-check just picks a
      // clearer message than the ILLEGAL_TRANSITION it would reject with.
      const current = store.getStatus(box).state;
      if (["FLASHING", "RESETTING", "IN_SESSION"].includes(current)) {
        set(box, {
          phase: "done",
          tier: "failed",
          detail: "the box is busy — flashing, resetting, or in a session",
        });
        return;
      }
      if (current === "ERROR") {
        set(box, {
          phase: "done",
          tier: "failed",
          detail: "the box is in an error state — acknowledge it in Debug Mode first",
        });
        return;
      }

      inFlight.current.add(box);
      set(box, { phase: "running" });

      let sawRx = false;
      let lineCount = 0;
      let resolveReady: (() => void) | null = null;
      // Subscribe before opening: boot output starts the instant the open
      // asserts DTR, and the first batch would otherwise race the listener.
      const off = client.on(EVT.PORT_OUTPUT, (data) => {
        const d = data as { box: number; lines: Array<{ dir: string; text: string }> };
        if (d.box !== box) return;
        for (const line of d.lines) {
          if (line.dir !== "rx") continue;
          sawRx = true;
          lineCount += 1;
          if (READY_RE.test(line.text.trim())) resolveReady?.();
        }
      });

      let opened = false;
      try {
        // A port already in passthrough is closed first: re-opening is what
        // makes the DTR reset (and therefore the boot banner) happen, and a
        // stale handler must never survive into the test.
        if (current === "PASSTHROUGH") {
          await client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box });
        }
        await client.call(CMD.PORT_PASSTHROUGH_OPEN, { box, baud: settings.defaultBaud });
        opened = true;

        const sawReady = await new Promise<boolean>((resolve) => {
          const timer = setTimeout(() => resolve(false), LISTEN_MS);
          resolveReady = () => {
            clearTimeout(timer);
            resolve(true);
          };
        });

        if (sawReady) {
          set(box, { phase: "done", tier: "ready", detail: "READY received — speaks Ephymeris" });
        } else if (sawRx) {
          set(box, {
            phase: "done",
            tier: "output",
            detail: `board responded (${lineCount} line${lineCount === 1 ? "" : "s"}), no READY — not an Ephymeris task sketch?`,
          });
        } else {
          set(box, {
            phase: "done",
            tier: "silent",
            detail: `port opened at ${settings.defaultBaud} baud but the board said nothing — wrong baud or a blank sketch?`,
          });
        }
      } catch (err) {
        const code = err instanceof SidecarCommandError ? err.code : "INTERNAL";
        set(box, {
          phase: "done",
          tier: "failed",
          detail: FAILED_DETAIL[code] ?? (err instanceof Error ? err.message : String(err)),
        });
      } finally {
        off();
        resolveReady = null;
        if (opened) {
          await client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }).catch(() => {});
        }
        inFlight.current.delete(box);
      }
    },
    [client, settings.defaultBaud, set, store],
  );

  const stateFor = useCallback(
    (box: number): HandshakeState => states.get(box) ?? { phase: "idle" },
    [states],
  );

  return { run, stateFor, anyRunning: [...states.values()].some((s) => s.phase === "running") };
}
