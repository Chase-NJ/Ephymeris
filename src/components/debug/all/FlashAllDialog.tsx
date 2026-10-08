import { Check, CircleAlert, Loader2, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { useHardwareStore } from "@/lib/hardware/context";
import type { PortStateName } from "@/lib/ws/protocol";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { CMD, EVT } from "@/lib/ws/protocol";

/** How long one box may stay busy (a baseline restore, say) before its turn. */
const PORT_WAIT_MS = 180_000;

type Step = { state: "waiting" | "flashing" | "done" | "failed"; detail: string };

/**
 * Flash one sketch to every targeted box — **one box at a time**.
 *
 * Two `arduino-cli` builds at once are slower than one after the other, and a
 * box mid-restore must be left to finish (`ARCHITECTURE.md#flash-sequence`),
 * so this is a queue: each box waits until its port is free, flashes, and
 * reopens its console, as a single-box flash from Debug does. Every flash
 * from Debug pins its box (`ARCHITECTURE.md#three-rules-it-never-breaks`);
 * "Return to baseline" undoes that for the lot.
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
  const store = useHardwareStore();
  const [selected, setSelected] = useState<string | null>(null);
  const [steps, setSteps] = useState<Map<number, Step> | null>(null);
  const [current, setCurrent] = useState<number | null>(null);
  const [lastLine, setLastLine] = useState("");
  const cancelled = useRef(false);

  useEffect(() => {
    if (open) {
      setSteps(null);
      setCurrent(null);
      setLastLine("");
      cancelled.current = false;
    }
  }, [open]);

  useEffect(() => {
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

  const set = (box: number, step: Step) =>
    setSteps((prev) => new Map(prev ?? []).set(box, step));

  async function waitForPort(box: number): Promise<void> {
    const free = (s: PortStateName) => s === "IDLE" || s === "PASSTHROUGH";
    const started = Date.now();
    while (!free(store.getStatus(box).state)) {
      if (cancelled.current) throw new Error("cancelled");
      if (Date.now() - started > PORT_WAIT_MS) throw new Error("the port stayed busy");
      await new Promise((r) => setTimeout(r, 500));
    }
  }

  async function flashAll() {
    if (!selected) return;
    const name = discovery.sketches.find((s) => s.path === selected)?.name ?? selected;
    setSteps(new Map(boxes.map((b) => [b, { state: "waiting", detail: "queued" }])));
    for (const box of boxes) {
      if (cancelled.current) break;
      setCurrent(box);
      setLastLine("");
      try {
        await waitForPort(box);
        set(box, { state: "flashing", detail: "compiling and uploading" });
        const res = (await client.call(CMD.PORT_FLASH, { box, sketchPath: selected })) as {
          resumedPassthrough: boolean;
        };
        store.setFlashed(box, { path: selected, name });
        if (!res.resumedPassthrough) {
          await client.call(CMD.PORT_PASSTHROUGH_OPEN, { box, baud }).catch(() => undefined);
        }
        set(box, { state: "done", detail: "flashed · console open" });
      } catch (err) {
        set(box, { state: "failed", detail: err instanceof Error ? err.message : String(err) });
      }
    }
    setCurrent(null);
  }

  const running = current !== null;
  const finished = steps !== null && !running;
  // Closing mid-queue lets the box in hand finish and flashes no more.
  const close = () => {
    if (running) cancelled.current = true;
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title={`Flash ${boxes.length} box${boxes.length === 1 ? "" : "es"}`}
      size="md"
    >
      {steps === null ? (
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
              const step = steps.get(box);
              return (
                <li key={box} className="flex items-center gap-2 font-mono text-[11px]">
                  <span className="w-12 text-static">Box {box}</span>
                  {step?.state === "flashing" ? (
                    <Loader2 size={12} className="animate-spin text-pulsar" />
                  ) : step?.state === "done" ? (
                    <Check size={12} className="text-ion" />
                  ) : step?.state === "failed" ? (
                    <CircleAlert size={12} className="text-status-error" />
                  ) : (
                    <span className="size-3" />
                  )}
                  <span className={step?.state === "failed" ? "text-status-error" : "text-static"}>
                    {step?.detail}
                  </span>
                </li>
              );
            })}
          </ul>
          {running && lastLine && (
            <p className="truncate border-t border-halo/60 pt-1.5 font-mono text-[10px] text-static/70">{lastLine}</p>
          )}
          <div className="flex justify-end">
            <Button variant={finished ? "primary" : "ghost"} onClick={close}>
              {finished ? "Done" : "Stop after this box"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
