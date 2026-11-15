import { Activity, CircleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { HudTile } from "@/components/common/HudTile";
import { Segmented } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { errorMessage } from "@/lib/cohorts/commands";
import { WINDOWS, binRates, describeSync, rankSites, siteMax, type WindowId } from "@/lib/intan/eventPsth";
import { useSidecar } from "@/lib/ws/context";
import { CMD, type EventPsth, type RunSummary } from "@/lib/ws/protocol";

/** One colour per group, from the six tokens: the first is the run's own. */
const GROUP_COLORS = [
  "var(--color-pulsar)",
  "var(--color-ion)",
  "var(--color-status-warning)",
  "var(--color-starlight)",
  "var(--color-static)",
];

type Split = EventPsth["split"];

/**
 * Spikes around a named behavioural event, after the session
 * (`RECORDING.md#event-psth`). RHX's own PSTH can only trigger on a digital
 * edge, and every event of a box pulses the same one; this aligns to the
 * event by NAME, from RHX's saved spikes and the run's strobes, every site at
 * once, split by trial condition or outcome.
 *
 * Renders nothing for a session with no recorded run. The first look at a run
 * reads its whole recording, which can take a while; later ones are served
 * from the sidecar's memory.
 */
export function EventPsthPanel({
  sessionId,
  runs,
  animalNames,
}: {
  sessionId: string;
  runs: readonly RunSummary[];
  animalNames: ReadonlyMap<string, string>;
}) {
  const { client, status } = useSidecar();
  const [recorded, setRecorded] = useState<string[] | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [code, setCode] = useState<number | null>(null);
  const [split, setSplit] = useState<Split>("none");
  const [windowId, setWindowId] = useState<WindowId>("mid");
  const [channel, setChannel] = useState<string | null>(null);
  const [view, setView] = useState<EventPsth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  useEffect(() => {
    if (status !== "connected") return;
    let cancelled = false;
    setRecorded(null);
    setView(null);
    void client
      .call(CMD.INTAN_RECORDED_RUNS, { sessionId })
      .then((reply) => {
        if (cancelled) return;
        setRecorded(reply.runIds);
        setRunId(reply.runIds[0] ?? null);
      })
      .catch(() => !cancelled && setRecorded([]));
    return () => {
      cancelled = true;
    };
  }, [client, status, sessionId]);

  const window_ = WINDOWS.find((w) => w.id === windowId) ?? WINDOWS[1];
  useEffect(() => {
    if (!runId || status !== "connected") return;
    const mine = ++request.current;
    setLoading(true);
    void client
      .call(CMD.INTAN_EVENT_PSTH, {
        runId,
        code,
        preMs: window_.preMs,
        postMs: window_.postMs,
        binMs: window_.binMs,
        split,
        rasterChannel: channel,
      })
      .then((reply) => {
        if (mine !== request.current) return;
        setView(reply);
        setError(null);
        // First look at a run: open on its most responsive site.
        if (channel === null) setChannel(rankSites(reply.sites)[0]?.channel ?? null);
      })
      .catch((err: unknown) => mine === request.current && setError(errorMessage(err)))
      .finally(() => mine === request.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, status, runId, code, split, windowId, channel]);

  const ranked = useMemo(() => (view ? rankSites(view.sites) : []), [view]);
  if (!recorded || recorded.length === 0) return null;

  const runOptions = recorded.map((id) => {
    const run = runs.find((r) => r.runId === id);
    const name = run ? (animalNames.get(run.animalId) ?? run.animalId) : id;
    return { value: id, label: run?.boxNumber ? `${name} · box ${run.boxNumber}` : name };
  });
  const sync = view ? describeSync(view.sync) : null;
  const selected = view?.sites.find((s) => s.channel === (view.rasterChannel ?? channel)) ?? null;

  return (
    <HudTile
      icon={Activity}
      label="Spikes around an event"
      status={
        sync ? (
          <span style={sync.trouble ? { color: "var(--color-status-warning)" } : undefined} title="Strobes matched to sync edges, over the whole run">
            {sync.text}
          </span>
        ) : loading ? (
          "reading the recording…"
        ) : null
      }
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-halo px-4 py-2.5">
        {runOptions.length > 1 && (
          <Dropdown
            label="Animal"
            value={runId ?? ""}
            options={runOptions}
            placeholder="— animal —"
            className="w-48"
            onChange={(id) => {
              setRunId(id);
              setChannel(null);
              setView(null);
            }}
          />
        )}
        {view && view.events.length > 0 && (
          <Dropdown
            label="Event"
            value={String(view.code ?? "")}
            options={view.events.map((e) => ({
              value: String(e.code),
              label: e.name,
              detail: e.placed === e.count ? `${e.count}` : `${e.placed}/${e.count} placed`,
            }))}
            placeholder="— event —"
            className="w-56"
            onChange={(v) => setCode(Number(v))}
          />
        )}
        <Segmented
          label="Split trials by"
          value={split}
          options={[
            { value: "none", label: "All" },
            { value: "condition", label: "Condition" },
            { value: "outcome", label: "Outcome" },
          ]}
          onChange={setSplit}
        />
        <Segmented
          label="Window"
          value={windowId}
          options={WINDOWS.map((w) => ({ value: w.id, label: w.label }))}
          onChange={setWindowId}
        />
        {loading && view && <span className="font-mono text-[10px] text-static">updating…</span>}
      </div>

      {error && (
        <p className="flex items-start gap-2 px-4 py-3 text-[12px]" style={{ color: "var(--color-status-error)" }}>
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          {error}
        </p>
      )}
      {!view && !error && (
        <p className="px-4 py-6 text-center text-[12px] text-static">
          Reading the recording — the first look at a run reads all of it, which can take a minute.
        </p>
      )}

      {view && (
        <div className="grid grid-cols-[200px_minmax(0,1fr)] gap-0">
          <ul className="max-h-[360px] overflow-y-auto border-r border-halo py-1">
            {ranked.map((site) => {
              const on = site.channel === selected?.channel;
              return (
                <li key={site.channel}>
                  <button
                    type="button"
                    onClick={() => setChannel(site.channel)}
                    className={`flex w-full items-center gap-2 px-3 py-1 text-left font-mono text-[11px] ${
                      on ? "bg-halo/60 text-starlight" : "text-static hover:text-starlight"
                    }`}
                  >
                    <span>{site.channel}</span>
                    <span
                      className="ml-auto"
                      style={{
                        color:
                          site.responsive === "up"
                            ? "var(--color-ion)"
                            : site.responsive === "down"
                              ? "var(--color-status-warning)"
                              : undefined,
                      }}
                    >
                      {site.responsive === "up" ? "▲" : site.responsive === "down" ? "▼" : "·"}{" "}
                      {site.t === null ? "–" : `t ${site.t.toFixed(1)}`}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="min-w-0 px-4 py-3">
            {selected ? <SiteChart psth={view} channel={selected.channel} /> : null}
          </div>
        </div>
      )}

      {view && (
        <div className="border-t border-halo px-4 py-2 text-[11px] leading-relaxed text-static">
          ▲▼ responsive: rate over the {view.responseMs} ms after the event differs from the {view.responseMs} ms
          before by |t| ≥ 3 — a first look, not a significance test. Spikes are RHX's threshold crossings.
          {view.eventsFile && (
            <span className="block truncate font-mono text-[10px]" title={view.eventsFile} data-selectable>
              events on the recording's clock: {view.eventsFile}
            </span>
          )}
        </div>
      )}
    </HudTile>
  );
}

const CHART_W = 560;
const PSTH_H = 140;
const ROW_H = 3;
const PAD = { left: 36, right: 8, top: 8, bottom: 18 };

/** One site: each group's rate per bin as a step line, then every trial's spikes. */
function SiteChart({ psth, channel }: { psth: EventPsth; channel: string }) {
  const site = psth.sites.find((s) => s.channel === channel);
  if (!site) return null;
  const top = siteMax(site, psth);
  const span = psth.preMs + psth.postMs;
  const plotW = CHART_W - PAD.left - PAD.right;
  const x = (ms: number) => PAD.left + ((ms + psth.preMs) / span) * plotW;
  const y = (hz: number) => PAD.top + (1 - hz / top) * (PSTH_H - PAD.top - PAD.bottom);
  const rasterRows = psth.rasters?.reduce((n, group) => n + group.length, 0) ?? 0;
  const rasterH = Math.min(220, rasterRows * ROW_H + 4);

  let row = 0;
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-3 font-mono text-[10px] text-static">
        <span className="text-starlight">{channel}</span>
        {psth.groups.map((g, i) => (
          <span key={g.label} className="flex items-center gap-1">
            <span className="inline-block h-[2px] w-3" style={{ background: GROUP_COLORS[i % GROUP_COLORS.length] }} />
            {g.label} · {g.trials} trials
          </span>
        ))}
        {site.deltaHz !== null && <span className="ml-auto">Δ {site.deltaHz.toFixed(1)} Hz</span>}
      </div>
      <svg viewBox={`0 0 ${CHART_W} ${PSTH_H}`} className="block w-full" role="img" aria-label={`PSTH for ${channel}`}>
        <line x1={x(0)} x2={x(0)} y1={PAD.top} y2={PSTH_H - PAD.bottom} stroke="var(--color-static)" strokeDasharray="2 3" />
        <line x1={PAD.left} x2={CHART_W - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--color-halo)" />
        <text x={PAD.left - 4} y={y(top) + 4} textAnchor="end" fontSize={9} fill="var(--color-static)" fontFamily="var(--font-mono)">
          {top} Hz
        </text>
        <text x={x(-psth.preMs)} y={PSTH_H - 4} fontSize={9} fill="var(--color-static)" fontFamily="var(--font-mono)">
          −{psth.preMs} ms
        </text>
        <text x={x(0)} y={PSTH_H - 4} textAnchor="middle" fontSize={9} fill="var(--color-static)" fontFamily="var(--font-mono)">
          0
        </text>
        <text x={CHART_W - PAD.right} y={PSTH_H - 4} textAnchor="end" fontSize={9} fill="var(--color-static)" fontFamily="var(--font-mono)">
          +{psth.postMs} ms
        </text>
        {site.counts.map((counts, g) => {
          const rates = binRates(counts, psth.groups[g]?.trials ?? 0, psth.binMs);
          const points = rates.flatMap((hz, k) => {
            const from = -psth.preMs + k * psth.binMs;
            return [`${x(from)},${y(hz)}`, `${x(from + psth.binMs)},${y(hz)}`];
          });
          return (
            <polyline
              key={g}
              points={points.join(" ")}
              fill="none"
              stroke={GROUP_COLORS[g % GROUP_COLORS.length]}
              strokeWidth={1.5}
            />
          );
        })}
      </svg>
      {psth.rasters && rasterRows > 0 && (
        <svg viewBox={`0 0 ${CHART_W} ${rasterH}`} className="mt-1 block w-full" role="img" aria-label={`Raster for ${channel}`}>
          <line x1={x(0)} x2={x(0)} y1={0} y2={rasterH} stroke="var(--color-static)" strokeDasharray="2 3" />
          {psth.rasters.map((group, g) =>
            group.map((trial) => {
              const yRow = 2 + (row++ * (rasterH - 4)) / Math.max(1, rasterRows);
              return trial.map((ms, k) => (
                <rect
                  key={`${g}-${row}-${k}`}
                  x={x(ms) - 0.5}
                  y={yRow}
                  width={1}
                  height={Math.max(1, ROW_H - 1)}
                  fill={GROUP_COLORS[g % GROUP_COLORS.length]}
                />
              ));
            }),
          )}
        </svg>
      )}
    </div>
  );
}
