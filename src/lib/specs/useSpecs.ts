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
 * The registry bundle, cached for the session.
 *
 * It is the vendored schema, overlay and registry FILES — it cannot change
 * while the app is running, because changing it means shipping a new build.
 * Held at module scope rather than in a provider so a route that needs it pays
 * for it once and a route that doesn't never asks. Cleared on disconnect is
 * unnecessary for the same reason: a reconnect is to the same sidecar binary.
 */
let schemaCache: SpecSchema | null = null;

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
  }, [client, connected]);

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
