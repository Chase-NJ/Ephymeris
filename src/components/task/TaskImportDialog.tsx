import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import { importTask } from "@/lib/taskdef/commands";
import { useSidecar } from "@/lib/ws/context";
import type { TaskImportPlan } from "@/lib/ws/protocol";

/**
 * Import a task exported on the lab's other machine
 * (`TASKS.md#moving-a-task-between-machines`).
 *
 * THE SIDECAR PLANS, THIS RENDERS, as `ChannelSetImportDialog` does. Every
 * conflict, the task it replaces and the diagnostics are in `tasks.import`'s
 * plan; nothing here predicts one. Import is held while the plan has a
 * conflict or is identical, and reads "Replace" while it `replaces` a saved
 * task, and the command checks all of it again inside the write. The import
 * never touches the channel set or the vocabulary.
 */
export function TaskImportDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const { client } = useSidecar();
  const [document, setDocument] = useState<unknown>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [plan, setPlan] = useState<TaskImportPlan | null>(null);
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
      setPlan((await importTask(client, parsed, false)).plan);
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
      // The task it replaces is named above the button, so pressing it is the confirm.
      await importTask(client, document, true, plan.replaces);
      onImported();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const conflicted = !!plan && plan.conflicts.length > 0;

  return (
    <Modal open={open} onClose={onClose} title="Import a task" size="lg">
      <div className="flex flex-col gap-3.5">
        <p className="text-[13px] leading-relaxed text-static">
          Bring in a task exported on the lab&rsquo;s other computer. It runs on this rig&rsquo;s
          own pins and records the same codes. Any disagreement about what the task uses — a
          channel missing or set up differently, the channels in another order, a code with
          another number — refuses the whole import.
        </p>
        <label className="flex cursor-pointer items-center gap-2 self-start rounded-sm border border-halo bg-nebula px-3 py-1.5 text-[12px] text-static transition-colors hover:border-static/70 hover:text-starlight">
          <Upload size={13} strokeWidth={1.75} />
          {fileName ?? "Choose an exported task…"}
          <input
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => void pick(e.target.files?.[0])}
          />
        </label>

        {plan && (
          <p className="text-[12px] text-static">
            <span className="text-starlight">{plan.name}</span>
            {plan.replaces && !plan.identical && " — replaces the task of that name saved here"}
          </p>
        )}

        {plan && conflicted && (
          <Callout
            title={`${plan.conflicts.length} conflict${plan.conflicts.length === 1 ? "" : "s"} — nothing can be imported`}
            tone="error"
            why="Resolve each on one of the two computers first, usually by importing the other computer's channel set on the Wiring page. Picking a winner here would record the task under other codes or on another line."
          >
            {plan.conflicts.map((c, i) => (
              <span key={`${c.kind}-${c.channel ?? ""}-${i}`} className="font-mono text-[10.5px] text-static">
                {c.message}
              </span>
            ))}
          </Callout>
        )}
        {plan && !conflicted && plan.diagnostics.length > 0 && (
          <Callout
            title={`${plan.diagnostics.length} problem${plan.diagnostics.length === 1 ? "" : "s"} on this rig`}
            tone="warning"
            why="It still imports, as a task with problems still saves; the editor shows what to fix."
          >
            {plan.diagnostics.map((d, i) => (
              <span key={`${d.code}-${i}`} className="font-mono text-[10.5px] text-static">
                {d.code} {d.location}: {d.message}
              </span>
            ))}
          </Callout>
        )}
        {plan?.identical && (
          <p className="text-[12px] text-static">
            Nothing to import — this rig already has exactly that task.
          </p>
        )}
        {plan && (
          <p className="font-mono text-[10.5px] text-static/80">
            {plan.sameChannelSet
              ? `channel set ${plan.hereHash}, the same on both`
              : `channel set ${plan.hereHash} here · ${plan.fileHash} there`}
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
            {busy ? "Importing…" : plan?.replaces ? "Replace" : "Import"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
