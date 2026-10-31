import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
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
 * of it again inside the write. The pins stay this machine's own.
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDocument(null);
    setFileName(null);
    setPlan(null);
    setError(null);
  }, [open]);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setFileName(file.name);
    setPlan(null);
    setError(null);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      setDocument(parsed);
      setPlan((await importChannelSet(client, parsed, false)).plan);
    } catch (err) {
      setDocument(null);
      setError(err instanceof SyntaxError ? "That file is not JSON." : errorMessage(err));
    }
  };

  const apply = async () => {
    if (!document || !plan) return;
    setBusy(true);
    setError(null);
    try {
      // `breaks` were shown above the button, so pressing it is the confirm.
      await importChannelSet(client, document, true, plan.breaks.length > 0);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const conflicted = !!plan && plan.conflicts.length > 0;
  const vocab = plan?.vocabulary;

  return (
    <Modal open={open} onClose={onClose} title="Import a channel set" size="lg">
      <div className="flex flex-col gap-3.5">
        <p className="text-[13px] leading-relaxed text-static">
          Make this rig&rsquo;s channels and strobe codes the other machine&rsquo;s, so both
          record the same task under the same numbers. The pins stay this rig&rsquo;s own. Any
          disagreement — one name with two codes, a channel one side lacks, the channels listed
          in another order — refuses the whole import.
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

        {plan && conflicted && (
          <Callout
            title={`${plan.conflicts.length} conflict${plan.conflicts.length === 1 ? "" : "s"} — nothing can be imported`}
            tone="error"
            why="Resolve each on one of the two machines first. Picking a winner here would relabel one machine's recorded data, leave a channel without a pin, or put another odor line behind an odor position — channel order is the odor index."
          >
            {plan.conflicts.map((c, i) => (
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
          <p className="font-mono text-[10.5px] text-static/80">
            channel set {plan.hereHash} here · {plan.thereHash} there
          </p>
        )}

        {error && <p className="text-[11.5px] text-status-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!plan || conflicted || plan.identical || busy}
            onClick={() => void apply()}
          >
            {busy ? "Importing…" : plan && plan.breaks.length > 0 ? "Import anyway" : "Import"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
