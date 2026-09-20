import { PlugZap } from "lucide-react";
import { useState } from "react";

import { Button, NumberInput } from "@/components/common/controls";
import { SettingRow } from "@/components/settings/SettingRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { useIntanStatus } from "@/lib/intan/context";
import { useSettings } from "@/lib/settings/context";
import { DEFAULT_INTAN } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

/**
 * The Rig tab's Recording tile body (`settings.md` §9): where Intan RHX's three
 * TCP servers listen, and a way to prove the link.
 *
 * On the RIG tab because it answers "what is this rig connected to", like the
 * box→board bindings above it — the per-box digital input lives in that table
 * for the same reason. There is no host field on purpose: Ephymeris only ever
 * talks to an RHX on this machine.
 */
export function RecordingPanel() {
  const { settings, update } = useSettings();
  const { client } = useSidecar();
  const intan = useIntanStatus();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ports = settings.intan ?? DEFAULT_INTAN;

  function setPort(key: keyof typeof ports, value: unknown) {
    const next = Number(value);
    if (!Number.isInteger(next) || next < 1 || next > 65535) return;
    void update({ intan: { ...ports, [key]: next } });
  }

  async function test() {
    setBusy(true);
    setError(null);
    try {
      await client.call(CMD.INTAN_CONNECT, {});
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const present = Object.entries(intan.ports)
    .filter(([, count]) => count > 0)
    .map(([letter, count]) => `${letter}:${count}`)
    .join("  ");

  return (
    <>
      <SettingRow
        label="Connection"
        description={
          intan.connected
            ? `${intan.controller ?? "Controller"} · RHX ${intan.version ?? "?"} · ${
                intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"
              }${intan.synthetic ? " · synthetic data" : ""}${present ? ` · headstage channels ${present}` : ""}`
            : "In RHX: Network → Remote TCP Control → Connect, on the Commands tab. That one click is the only manual step — Ephymeris opens RHX's two data sockets itself."
        }
      >
        <span className="flex items-center gap-2.5">
          <span
            className="flex items-center gap-1.5 font-mono text-[11px]"
            style={{ color: intan.connected ? "var(--color-ion)" : "var(--color-static)" }}
          >
            <span aria-hidden className="size-[7px] rounded-full bg-current" />
            {intan.connected ? "connected" : "not connected"}
          </span>
          <Button variant="outline" disabled={busy || intan.connected} onClick={() => void test()}>
            <PlugZap size={13} strokeWidth={1.75} />
            Connect
          </Button>
        </span>
      </SettingRow>

      {error && (
        <p className="border-b border-halo px-4 py-2.5 text-[12px]" style={{ color: "var(--color-status-error)" }}>
          {error}
        </p>
      )}
      {intan.connected && intan.confirmsWrites === false && (
        <p className="border-b border-halo px-4 py-2.5 text-[12px]" style={{ color: "var(--color-status-warning)" }}>
          This RHX does not confirm batched commands, so a refused setting cannot be detected. The save
          location, format and file name are still read back before every recording.
        </p>
      )}

      <SettingRow
        label="TCP ports"
        description="RHX's defaults. Change them only if they were changed in RHX's Remote TCP Control dialog."
      >
        <span className="flex items-center gap-2 text-[11px] text-static">
          commands
          <NumberInput
            label="RHX command port"
            value={ports.commandPort}
            fallback={DEFAULT_INTAN.commandPort}
            integer
            min={1}
            max={65535}
            className="w-[72px]"
            onChange={(v) => setPort("commandPort", v)}
          />
          waveform
          <NumberInput
            label="RHX waveform port"
            value={ports.waveformPort}
            fallback={DEFAULT_INTAN.waveformPort}
            integer
            min={1}
            max={65535}
            className="w-[72px]"
            onChange={(v) => setPort("waveformPort", v)}
          />
          spike
          <NumberInput
            label="RHX spike port"
            value={ports.spikePort}
            fallback={DEFAULT_INTAN.spikePort}
            integer
            min={1}
            max={65535}
            className="w-[72px]"
            onChange={(v) => setPort("spikePort", v)}
          />
        </span>
      </SettingRow>
    </>
  );
}
