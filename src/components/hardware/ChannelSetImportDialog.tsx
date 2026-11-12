import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import {
  canImport,
  latestOnly,
  type PinPicks,
  pinsToSend,
  refusals,
  withPick,
} from "@/lib/hardware/channelSetImport";
import { importChannelSet } from "@/lib/hardware/commands";
import { useSidecar } from "@/lib/ws/context";
import type { ChannelSetImportPlan } from "@/lib/ws/protocol";

/**
 * Import another lab machine's channel set and vocabulary
 * (`TASKS.md#moving-the-channel-set-between-machines`).
 *
 * THE SIDECAR PLANS, THIS RENDERS. Every conflict, every change and every task
 * the import would break is in `hardware.importChannelSet`'s plan; nothing here
 * predicts one. Import is held while the plan has a conflict or is identical,
 * and asks for confirmation while it has `breaks`, and the command checks all
 * of it again inside the write. The pins stay this machine's own, except a
 * channel the file adds: it takes a pin picked here from the plan's
 * `freePins`, and each pick re-plans, so a pin a wiring rule refuses is shown
 * before Import (`TASKS.md#adding-a-channel-lab-wide`).
 */
export function ChannelSetImportDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { client } = useSidecar();
  const [document, setDocument] = useState<unknown>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [plan, setPlan] = useState<ChannelSetImportPlan | null>(null);
  const [picks, setPicks] = useState<PinPicks>({});
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A reply to anything but the newest plan request is dropped.
  const requests = useRef(latestOnly());

  useEffect(() => {
    if (!open) return;
    requests.current.cancel();
    setDocument(null);
    setFileName(null);
    setPlan(null);
    setPicks({});
    setPending(false);
    setError(null);
  }, [open]);

  const replan = async (parsed: unknown, pins: Record<string, number>) => {
    const current = requests.current.begin();
    setPending(true);
    try {
      const reply = await importChannelSet(client, parsed, false, false, pins);
      if (current()) setPlan(reply.plan);
    } catch (err) {
      if (current()) {
        setPlan(null);
        setError(errorMessage(err));
      }
    } finally {
      if (current()) setPending(false);
    }
  };

  const pick = async (file: File | undefined) => {
    if (!file) return;
    // The last file's plan, if still on its way, is not this file's.
    requests.current.cancel();
    setPending(false);
    setFileName(file.name);
    setPlan(null);
    setPicks({});
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      setDocument(null);
      setError("That file is not JSON.");
      return;
    }
    setDocument(parsed);
    await replan(parsed, {});
  };

  const pinChannel = (channel: string, pin: number | null) => {
    const next = withPick(picks, channel, pin);
    setPicks(next);
    setError(null);
    void replan(document, pinsToSend(plan, next));
  };

  const apply = async () => {
    if (!document || !plan) return;
    setBusy(true);
    setError(null);
    try {
      // `breaks` were shown above the button, so pressing it is the confirm.
      await importChannelSet(client, document, true, plan.breaks.length > 0, pinsToSend(plan, picks));
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const conflicted = !!plan && plan.conflicts.length > 0;
  const refused = plan ? refusals(plan) : [];
  const vocab = plan?.vocabulary;

  return (
    <Modal open={open} onClose={onClose} title="Import a channel set" size="lg">
      <div className="flex flex-col gap-3.5">
        <p className="text-[13px] leading-relaxed text-static">
          Make this rig&rsquo;s channels and strobe codes the other machine&rsquo;s, so both
          record the same task under the same numbers. The pins stay this rig&rsquo;s own; a
          channel the file adds takes a pin you pick here. Any other disagreement — one name with
          two codes, a channel only this rig has, the channels listed in another order — refuses
          the whole import.
        </p>
        <label className="flex cursor-pointer items-center gap-2 self-start rounded-sm border border-halo bg-nebula px-3 py-1.5 text-[12px] text-static transition-colors hover:border-static/70 hover:text-starlight">
          <Upload size={13} strokeWidth={1.75} />
          {fileName ?? "Choose an exported channel set…"}
          <input
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => void pick(e.target.files?.[0])}
          />
        </label>

        {plan && plan.newChannels.length > 0 && (
          <Callout
            title={`${plan.newChannels.length} channel${plan.newChannels.length === 1 ? "" : "s"} to add — pick a pin for each`}
            why="The pin map is this rig's own. The pins offered are free on this board; the import checks your picks against the wiring rules, as a save does."
          >
            {plan.newChannels.map((c) => (
              <label key={c.channel} className="flex items-center gap-3 font-mono text-[11px]">
                <span className="w-32 truncate text-starlight">{c.channel}</span>
                <span className="w-32 truncate text-static">
                  {c.kind ?? "?"} · {c.type ?? "?"}
                </span>
                <select
                  className="rounded-sm border border-halo bg-nebula px-2 py-0.5 text-[11px] text-starlight"
                  value={picks[c.channel] ?? ""}
                  disabled={busy}
                  onChange={(e) =>
                    pinChannel(c.channel, e.target.value === "" ? null : Number(e.target.value))
                  }
                >
                  <option value="">Pick a pin…</option>
                  {c.freePins.map((pin) => (
                    <option key={pin} value={pin}>
                      pin {pin}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </Callout>
        )}
        {plan && refused.length > 0 && (
          <Callout
            title={`${refused.length} conflict${refused.length === 1 ? "" : "s"} — nothing can be imported`}
            tone="error"
            why="A pin picked here can be changed above. Anything else is resolved on one of the two machines first: picking a winner here would relabel one machine's recorded data, or put another odor line behind an odor position — channel order is the odor index."
          >
            {refused.map((c, i) => (
              <span key={`${c.kind}-${c.channel ?? ""}-${i}`} className="font-mono text-[10.5px] text-static">
                {c.message}
              </span>
            ))}
          </Callout>
        )}
        {plan && !conflicted && plan.changed.length > 0 && (
          <Callout title={`${plan.changed.length} channel${plan.changed.length === 1 ? "" : "s"} change`}>
            <span className="font-mono text-[11px] text-starlight">{plan.changed.join(", ")}</span>
          </Callout>
        )}
        {vocab && !conflicted && vocab.adds.length > 0 && (
          <Callout title={`${vocab.adds.length} code${vocab.adds.length === 1 ? "" : "s"} to add`}>
            {vocab.adds.map((a) => (
              <div key={a.name} className="flex items-baseline gap-2 font-mono text-[11px]">
                <span className="w-10 text-right text-static">{a.code}</span>
                <span className="text-starlight">{a.name}</span>
              </div>
            ))}
          </Callout>
        )}
        {vocab && !conflicted && vocab.retires.length > 0 && (
          <Callout
            title={`${vocab.retires.length} code${vocab.retires.length === 1 ? "" : "s"} to retire`}
            tone="warning"
            why="Retired on the other machine, live here. Retiring travels: some session there contains the code and its emitter is gone."
          >
            {vocab.retires.map((r) => (
              <div key={r.name} className="flex items-baseline gap-2 font-mono text-[11px]">
                <span className="w-10 text-right text-static">{r.code}</span>
                <span className="text-starlight">{r.name}</span>
              </div>
            ))}
          </Callout>
        )}
        {plan && !conflicted && plan.breaks.length > 0 && (
          <Callout
            title={`Stops ${plan.breaks.length} saved task${plan.breaks.length === 1 ? "" : "s"} compiling`}
            tone="warning"
            why="Importing anyway is your call; the tasks show what to fix afterwards."
          >
            {plan.breaks.map((b) => (
              <span key={b.specId} className="font-mono text-[10.5px] text-static">
                {b.label ?? b.specId}: {b.codes.join(", ")}
              </span>
            ))}
          </Callout>
        )}
        {plan?.identical && (
          <p className="text-[12px] text-static">
            Nothing to import — this rig already has that channel set and every code in it.
          </p>
        )}
        {plan && (
          // Both computed here, by the current rule. The file's own hash is
          // shown only when it was made by another rule, so two numbers that
          // differ never read as a disagreement they are not.
          <p className="font-mono text-[10.5px] text-static/80">
            channel set {plan.hereHash} now · {plan.importedHash} after import
            {plan.fileHash !== plan.importedHash &&
              ` · the file says ${plan.fileHash} (hash version ${plan.fileHashVersion})`}
          </p>
        )}

        {error && <p className="text-[11.5px] text-status-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!canImport(plan, pending) || busy}
            onClick={() => void apply()}
          >
            {busy ? "Importing…" : plan && plan.breaks.length > 0 ? "Import anyway" : "Import"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
