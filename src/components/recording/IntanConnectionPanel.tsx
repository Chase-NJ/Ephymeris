import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, PlugZap, Unplug } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, NumberInput } from "@/components/common/controls";
import { SettingRow } from "@/components/settings/SettingRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { useIntanStatus } from "@/lib/intan/context";
import { useSettings } from "@/lib/settings/context";
import { springSnappy } from "@/lib/motion";
import { DEFAULT_INTAN } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

/**
 * The Recording tab's Connection tile body (`RECORDING.md#talking-to-rhx`): the
 * link to Intan RHX, the one click in RHX that opens it, and where its three
 * TCP servers listen.
 *
 * On the RECORDING tab, beside the box→input bindings and the recording
 * defaults, because the person setting it up is setting up a recording — the
 * Rig tab is for the boxes themselves. There is no host field on purpose:
 * Ephymeris only ever talks to an RHX on this machine.
 */
export function IntanConnectionPanel() {
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

  async function call(cmd: typeof CMD.INTAN_CONNECT | typeof CMD.INTAN_DISCONNECT) {
    setBusy(true);
    setError(null);
    try {
      await client.call(cmd, {});
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
  const recording = intan.state === "recording" || intan.state === "stopping";

  return (
    <>
      <SettingRow
        label="Connection"
        description={
          intan.connected
            ? `${intan.controller ?? "Controller"} · RHX ${intan.version ?? "?"} · ${
                intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"
              }${present ? ` · headstage ${present}` : " · no headstage"}`
            : "Ephymeris keeps trying every second. RHX has to open its door first — see below."
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
          {intan.connected && intan.synthetic && (
            <span
              className="rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[10px] text-static"
              title="RHX is generating its data — no controller is attached. The sync-line check is off and events are aligned by arrival."
            >
              synthetic
            </span>
          )}
          {intan.connected ? (
            <Button
              variant="ghost"
              disabled={busy || recording}
              title={recording ? "A recording is running; end it first." : "Close Ephymeris' sockets to RHX"}
              onClick={() => void call(CMD.INTAN_DISCONNECT)}
            >
              <Unplug size={13} strokeWidth={1.75} />
              Disconnect
            </Button>
          ) : (
            <Button variant="outline" disabled={busy} onClick={() => void call(CMD.INTAN_CONNECT)}>
              <PlugZap size={13} strokeWidth={1.75} />
              Connect
            </Button>
          )}
        </span>
      </SettingRow>

      <SetupSteps defaultOpen={!intan.connected} />

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

/**
 * The one manual step in RHX, folded into a disclosure: open while there is no
 * link (that is when it is needed), closed once RHX answers — and it follows
 * the link, so a dropped connection brings it back.
 */
function SetupSteps({ defaultOpen }: { defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => setOpen(defaultOpen), [defaultOpen]);
  return (
    <div className="border-b border-halo/70">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-4 py-2 text-left font-mono text-[10px] tracking-[0.14em] text-static uppercase transition-colors hover:text-starlight"
      >
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={springSnappy} className="flex">
          <ChevronRight size={12} strokeWidth={1.75} />
        </motion.span>
        How to connect
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springSnappy}
            className="flex flex-col gap-1 overflow-hidden px-4 text-[12px] leading-relaxed text-static"
          >
            <Step n={1}>
              In RHX, open <span className="text-starlight">Network → Remote TCP Control</span>.
            </Step>
            <Step n={2}>
              On the <span className="text-starlight">Commands</span> tab, press{" "}
              <span className="text-starlight">Connect</span>. That is the only manual step.
            </Step>
            <Step n={3}>
              Ephymeris opens RHX's two data sockets itself. RHX closes its door whenever a client
              leaves, so the click is needed again after every disconnect.
            </Step>
            <li aria-hidden className="h-2" />
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="mt-px w-4 shrink-0 font-mono text-[10px] text-static/70">{n}.</span>
      <span>{children}</span>
    </li>
  );
}
