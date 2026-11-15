import { useCallback, useEffect, useMemo, useState } from "react";

import { Segmented } from "@/components/common/controls";
import { ProbeMapView } from "@/components/recording/ProbeMapView";
import { messageOf, useScope } from "@/lib/intan/context";
import type { ProbeMap, ProbeRatesPayload, ScopeData } from "@/lib/intan/types";
import { openScopeWindow, scopeTitle } from "@/lib/intan/windows";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

import { useScopeContext } from "./ScopeApp";
import { ScopeFrame, Waiting } from "./ScopeFrame";

/**
 * The box's probe, with each site lit by how much it fired in the last second.
 *
 * RHX can show a probe map but cannot be told to load one over TCP, so this
 * draws the same XML file the operator picked at setup. Clicking a site opens
 * that channel's Spike Scope — the map is the fastest channel picker there is
 * once the question is "what is happening at *this depth*".
 */
export function ProbeMapWindow() {
  const ctx = useScopeContext();
  const { client, status } = useSidecar();
  const [map, setMap] = useState<ProbeMap | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [rates, setRates] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "connected" || ctx.box <= 0) return;
    let cancelled = false;
    void client
      .call(CMD.INTAN_PROBE_MAP, { box: ctx.box })
      .then((reply) => {
        if (cancelled) return;
        if (reply.probeMap) setMap(reply.probeMap as ProbeMap);
        else setMissing("No probe map was added for this box at the recording step.");
      })
      .catch((err: unknown) => !cancelled && setMissing(messageOf(err)));
    return () => {
      cancelled = true;
    };
  }, [client, status, ctx.box]);

  // Rates change a few times a second and there are at most a few hundred
  // sites, so — unlike the SpikeScope — this one can simply be React state.
  const onData = useCallback((message: ScopeData) => {
    setRates((message.data as ProbeRatesPayload).rates);
  }, []);
  const params = useMemo(() => ({}), []);
  const scope = useScope("probemap", ctx.box, null, params, onData);

  const active = Object.values(rates).filter((r) => r > 0).length;
  const busiest = Object.entries(rates).reduce<[string, number] | null>(
    (best, entry) => (entry[1] > (best?.[1] ?? 0) ? entry : best),
    null,
  );

  function openSite(channel: string) {
    setSelected(channel);
    openScopeWindow("spikescope", ctx.box, { animal: ctx.animal, channel });
  }

  return (
    <ScopeFrame
      title={scopeTitle("probemap", ctx.box, ctx.animal)}
      subtitle={map?.name}
      error={scope.error}
      options={
        map && map.pages.length > 1 ? (
          <Segmented
            label="Probe map page"
            value={String(page)}
            options={map.pages.map((p, i) => ({ value: String(i), label: p.name }))}
            onChange={(v) => setPage(Number(v))}
          />
        ) : undefined
      }
      status={
        <>
          <span>
            {active}/{ctx.channels.length} sites firing
          </span>
          {busiest && (
            <span>
              busiest {busiest[0]} · {busiest[1]} Hz
            </span>
          )}
          <span className="ml-auto">click a site for its Spike Scope</span>
        </>
      }
    >
      {map ? (
        <ProbeMapView
          map={map}
          page={page}
          rates={rates}
          channels={ctx.channels}
          selected={selected}
          onSelect={openSite}
          legend
          className="absolute inset-0"
        />
      ) : (
        <Waiting detail={missing ? "add one on the Record step next time" : undefined}>
          {missing ?? "Loading the probe map…"}
        </Waiting>
      )}
    </ScopeFrame>
  );
}
