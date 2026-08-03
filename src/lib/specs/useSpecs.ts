import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";
import { getCapabilities, getSpecSchema, listSpecs } from "./commands";
import type { SpecCapabilities, SpecEntry, SpecSchema } from "./types";

/**
 * The spec library and the form's schema bundle, for the Task route.
 *
 * Mounted at the route rather than the app root, deliberately: HardwareProvider
 * lives at the root because the sidebar needs box health on every screen, and
 * that reasoning cuts the other way here — nothing outside /task reads specs.
 *
 * `unavailable` carries the SPEC_COMPILER_UNAVAILABLE story: the list call is
 * the probe, and its failure message is rendered as the one banner. The list
 * also arrives on `specs.updated` (replayed on connect), so a reconnect heals
 * without a refetch.
 */
export function useSpecs(): {
  specs: SpecEntry[];
  schema: SpecSchema | null;
  unavailable: string | null;
  loading: boolean;
} {
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [specs, setSpecs] = useState<SpecEntry[]>([]);
  const [schema, setSchema] = useState<SpecSchema | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(
    () =>
      client.on(EVT.SPECS_UPDATED, (data) => {
        setSpecs((data as { specs: SpecEntry[] }).specs);
        setUnavailable(null);
      }),
    [client],
  );

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const [entries, bundle] = await Promise.all([
          listSpecs(client),
          getSpecSchema(client),
        ]);
        if (cancelled) return;
        setSpecs(entries);
        setSchema(bundle);
        setUnavailable(null);
      } catch (err) {
        if (!cancelled) setUnavailable(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, connected]);

  return { specs, schema, unavailable, loading };
}

/**
 * `capabilities(topology)`, re-asked on every knob change. No debounce — it is
 * a pure function of six scalars and is exactly what must answer BEFORE the
 * compile does, so the timing rows and outcome cards re-gate the instant a
 * knob moves.
 */
export function useCapabilities(
  topology: Record<string, unknown> | null,
): SpecCapabilities | null {
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const [caps, setCaps] = useState<SpecCapabilities | null>(null);

  // The knobs, not the object identity: setAt() rebuilds the topology object
  // on every edit anywhere in the document, and re-asking for an unchanged
  // answer would defeat the point of the gate being instant.
  const knobsKey = useMemo(() => JSON.stringify(topology ?? {}), [topology]);

  useEffect(() => {
    if (!connected || topology === null) {
      setCaps(null);
      return;
    }
    let cancelled = false;
    void getCapabilities(client, JSON.parse(knobsKey) as Record<string, unknown>)
      .then((reply) => {
        if (!cancelled) setCaps(reply);
      })
      .catch(() => {
        // A malformed half-built topology (unknown template mid-typing) is not
        // an error state worth a banner; the compile's diagnostics cover it.
        if (!cancelled) setCaps(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, connected, knobsKey]);

  return caps;
}
