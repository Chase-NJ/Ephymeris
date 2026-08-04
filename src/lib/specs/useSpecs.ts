import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";
import { getCapabilities, getParadigms, getSpecSchema, listSpecs } from "./commands";
import type { ParadigmSummary, SpecCapabilities, SpecEntry, SpecSchema } from "./types";

/**
 * The spec library and the form's schema bundle, for the Task routes.
 *
 * Mounted per route rather than at the app root, deliberately: HardwareProvider
 * lives at the root because the sidebar needs box health on every screen, and
 * that reasoning cuts the other way here — nothing outside /task reads specs.
 * Four `/task/*` routes now share this hook, and moving between them remounts
 * it; the schema cache below is what keeps that from costing a round trip each
 * time, without making the whole app carry the state.
 *
 * `unavailable` carries the SPEC_COMPILER_UNAVAILABLE story: the list call is
 * the probe, and its failure message is rendered as the one banner. The list
 * also arrives on `specs.updated` (replayed on connect), so a reconnect heals
 * without a refetch.
 */
/*
 * The registry bundle, cached for the session — and invalidated when the rig is
 * rewired.
 *
 * It USED to be true that this could not change while the app was running: the
 * bundle is the schema, the overlay and the registry files, and changing those
 * meant shipping a new build. That is still true of four of its five members.
 * `channels` is now the composed channel map, which an operator can edit from
 * Task → Rig wiring, so a cache held for the session would leave every channel
 * picker in the app offering pins that moved.
 *
 * Held at module scope rather than in a provider so a route that needs it pays
 * for it once and a route that doesn't never asks. Still not cleared on
 * disconnect: a reconnect is to the same sidecar binary, and the wiring it is
 * running announces itself on `hardware.updated`.
 */
let schemaCache: SpecSchema | null = null;

/** Drop the bundle so the next mount refetches it. Exported for the rig editor,
 * which knows it changed before any hook here does. */
export function invalidateSpecSchema(): void {
  schemaCache = null;
}

export function useSpecs(): {
  specs: SpecEntry[];
  schema: SpecSchema | null;
  unavailable: string | null;
  loading: boolean;
} {
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [specs, setSpecs] = useState<SpecEntry[]>([]);
  const [schema, setSchema] = useState<SpecSchema | null>(schemaCache);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);

  useEffect(
    () =>
      client.on(EVT.SPECS_UPDATED, (data) => {
        setSpecs((data as { specs: SpecEntry[] }).specs);
        setUnavailable(null);
      }),
    [client],
  );

  /* The wiring moved, so `channels` in the cached bundle describes pins that
   * are no longer where it says. Refetch rather than patch: the bundle is the
   * compiler's composed answer, and reconstructing half of it here would be the
   * frontend holding its own copy of a registry — the one thing `specs.schema`
   * exists to prevent. */
  useEffect(
    () =>
      client.on(EVT.HARDWARE_UPDATED, () => {
        invalidateSpecSchema();
        setRefresh((n) => n + 1);
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
          // The list call is the availability probe either way, so a cached
          // schema saves the second round trip without weakening that.
          schemaCache ? Promise.resolve(schemaCache) : getSpecSchema(client),
        ]);
        if (cancelled) return;
        schemaCache = bundle;
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
  }, [client, connected, refresh]);

  return { specs, schema, unavailable, loading };
}

/*
 * The paradigm catalogue, cached for the session alongside the schema.
 *
 * Static for the life of the process for the same reason the schema is: these
 * are shipped files, and changing them means shipping a new build. They used to
 * be a hardcoded table in the frontend, which could only ever name tasks that
 * already shipped — and once nothing ships, that table could name nothing at
 * all.
 */
let paradigmCache: ParadigmSummary[] | null = null;

export function useParadigms(): {
  paradigms: ParadigmSummary[];
  loading: boolean;
  error: string | null;
} {
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const [paradigms, setParadigms] = useState<ParadigmSummary[]>(paradigmCache ?? []);
  const [loading, setLoading] = useState(paradigmCache === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!connected || paradigmCache !== null) return;
    let cancelled = false;
    void getParadigms(client)
      .then((list) => {
        if (cancelled) return;
        paradigmCache = list;
        setParadigms(list);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, connected]);

  return { paradigms, loading, error };
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
