import { Check, CircleAlert, Loader2, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import { useFlashQueue } from "@/lib/hardware/context";
import type { FlashJobStatus } from "@/lib/hardware/store";
import { cancelFlashes, enqueueFlash } from "@/lib/hardware/commands";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

const IN_HAND: ReadonlySet<FlashJobStatus["state"]> = new Set(["queued", "waiting", "flashing"]);

/**
 * Flash one sketch to every targeted box — **one box at a time**.
 *
 * The sidecar runs it (`ARCHITECTURE.md#the-flash-queue`): each box waits
 * until its port is free, flashes, and reopens its console, as a single-box
 * flash from Debug does, and one failure does not stop the rest. This dialog
 * only asks and shows, so closing it — or leaving Debug Mode — stops nothing;
 * reopening it shows the queue again. "Stop after this box" drops what is
 * still queued. Every flash from Debug pins its box
 * (`ARCHITECTURE.md#three-rules-it-never-breaks`); "Return to baseline" undoes
 * that for the lot.
 */
export function FlashAllDialog({
  open,
  boxes,
  baud,
  onClose,
}: {
  open: boolean;
  boxes: readonly number[];
  baud: number;
  onClose: () => void;
}) {
  const { client } = useSidecar();
  const { discovery } = useSettings();
  const queue = useFlashQueue();
  const [selected, setSelected] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastLine, setLastLine] = useState("");

  /** Each targeted box's Debug flash, as the sidecar reports it. */
  const jobs = useMemo(() => {
    const rows = new Map(queue.boxes.map((row) => [row.box, row.job]));
    return new Map(
      boxes.map((box) => {
        const job = rows.get(box);
        return [box, job?.origin === "debug" ? job : null] as const;
      }),
    );
  }, [queue, boxes]);
  const running = boxes.some((box) => {
    const job = jobs.get(box);
    return job !== null && job !== undefined && IN_HAND.has(job.state);
  });
  const current = boxes.find((box) => jobs.get(box)?.state === "flashing") ?? null;

  useEffect(() => {
    if (open) {
      setSubmitted(false);
      setError(null);
      setLastLine("");
    }
  }, [open]);

  useEffect(() => {
    setLastLine("");
    if (current === null) return;
    return client.on(EVT.FLASH_PROGRESS, (data) => {
      const d = data as { box: number; text: string };
      if (d.box === current && d.text.trim()) setLastLine(d.text.trim());
    });
  }, [client, current]);

  const byCategory = useMemo(() => {
    const groups = new Map<string, typeof discovery.sketches>();
    for (const sketch of discovery.sketches) {
      groups.set(sketch.category, [...(groups.get(sketch.category) ?? []), sketch]);
    }
    return [...groups.entries()];
  }, [discovery.sketches]);

  async function flashAll() {
    if (!selected) return;
    setError(null);
    try {
      await enqueueFlash(client, boxes, selected, baud);
      setSubmitted(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  // A queue already under way for these boxes is shown, not offered again.
  const showing = submitted || running;
  const finished = showing && !running;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Flash ${boxes.length} box${boxes.length === 1 ? "" : "es"}`}
      size="md"
    >
      {!showing ? (
        <div className="flex flex-col gap-3">
          <p className="text-[12px] leading-relaxed text-static">
            One sketch to every targeted box, one box at a time. Each box is pinned to it until you
            return the rig to its baseline.
          </p>
          <div className="scrollbar-slim flex max-h-[320px] flex-col gap-2 overflow-y-auto">
            {byCategory.map(([category, sketches]) => (
              <section key={category}>
                <h3 className="mb-1 font-mono text-[9px] tracking-[0.16em] text-static/70 uppercase">{category}</h3>
                <div className="flex flex-col">
                  {sketches.map((sketch) => (
                    <button
                      key={sketch.path}
                      type="button"
                      onClick={() => setSelected(sketch.path)}
                      className={`rounded-sm border-y px-2 py-1 text-left text-[12px] transition-colors ${
                        selected === sketch.path
                          ? "border-pulsar/40 bg-pulsar/10 text-starlight"
                          : "border-transparent text-static hover:bg-halo/30 hover:text-starlight"
                      }`}
                    >
                      {sketch.name}
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
          {error && <p className="text-[12px] text-status-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" disabled={!selected || boxes.length === 0} onClick={() => void flashAll()}>
              <Zap size={12} strokeWidth={2} />
              Flash {boxes.length}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col gap-1">
            {boxes.map((box) => {
              const job = jobs.get(box) ?? null;
              return (
                <li key={box} className="flex items-center gap-2 font-mono text-[11px]">
                  <span className="w-12 text-static">Box {box}</span>
                  {job?.state === "flashing" ? (
                    <Loader2 size={12} className="animate-spin text-pulsar" />
                  ) : job?.state === "done" ? (
                    <Check size={12} className="text-ion" />
                  ) : job?.state === "failed" ? (
                    <CircleAlert size={12} className="text-status-error" />
                  ) : (
                    <span className="size-3" />
                  )}
                  <span className={job?.state === "failed" ? "text-status-error" : "text-static"}>
                    {stepText(job)}
                  </span>
                </li>
              );
            })}
          </ul>
          {current !== null && lastLine && (
            <p className="truncate border-t border-halo/60 pt-1.5 font-mono text-[10px] text-static/70">{lastLine}</p>
          )}
          <div className="flex justify-end gap-2">
            {running && (
              <Button
                variant="ghost"
                onClick={() => void cancelFlashes(client, boxes).catch((err) => setError(errorMessage(err)))}
              >
                Stop after this box
              </Button>
            )}
            <Button variant={finished ? "primary" : "ghost"} onClick={onClose}>
              {finished ? "Done" : "Close"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

/** One box's line: what its Debug flash is doing, in the sidecar's words. */
function stepText(job: FlashJobStatus | null): string {
  if (job === null) return "not queued";
  switch (job.state) {
    case "queued":
      return "queued";
    case "waiting":
      return job.detail ?? "waiting for the port";
    case "flashing":
      return "compiling and uploading";
    case "done":
      return job.detail ? `flashed · ${job.detail}` : "flashed";
    case "failed":
      return job.detail ?? "failed";
  }
}
