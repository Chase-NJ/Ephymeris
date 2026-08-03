import { Check, CircleAlert, RefreshCw, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { useHardwareStore } from "@/lib/hardware/context";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { CMD, EVT } from "@/lib/ws/protocol";

/**
 * The flashing flow (`dashboard.md` §6.1): pick a sketch from the
 * categorized list discovered in the configured Arduino Directory, then watch
 * compile/upload progress stream in — not a spinner-until-done.
 *
 * The list is the only path to a flashable sketch (`tasks.md` §2.3),
 * and all four directory states from §6 render distinctly here. The sidecar
 * enforces list membership too; this UI is the convenient face of that rule,
 * not the rule itself.
 */

interface ProgressEntry {
  id: number;
  phase: "compile" | "upload";
  stream: string;
  text: string;
}

type Stage = "pick" | "flashing" | "done";

export function FlashDialog({
  box,
  open,
  onClose,
}: {
  box: number;
  open: boolean;
  onClose: () => void;
}) {
  const { client } = useSidecar();
  const { discovery, refreshSketches } = useSettings();
  const store = useHardwareStore();

  const [selected, setSelected] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("pick");
  const [log, setLog] = useState<ProgressEntry[]>([]);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const seq = useRef(0);

  // Fresh start each time the dialog opens.
  useEffect(() => {
    if (open) {
      setStage("pick");
      setLog([]);
      setResult(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    return client.on(EVT.FLASH_PROGRESS, (data) => {
      const d = data as { box: number } & Omit<ProgressEntry, "id">;
      if (d.box !== box) return;
      seq.current += 1;
      setLog((prev) => [
        ...prev.slice(-499),
        { id: seq.current, phase: d.phase, stream: d.stream, text: d.text },
      ]);
    });
  }, [client, open, box]);

  const byCategory = useMemo(() => {
    const groups = new Map<string, typeof discovery.sketches>();
    for (const sketch of discovery.sketches) {
      const list = groups.get(sketch.category) ?? [];
      list.push(sketch);
      groups.set(sketch.category, list);
    }
    return [...groups.entries()];
  }, [discovery.sketches]);

  async function flash() {
    if (!selected) return;
    setStage("flashing");
    setLog([]);
    try {
      const res = (await client.call(CMD.PORT_FLASH, { box, sketchPath: selected })) as {
        resumedPassthrough: boolean;
      };
      // Remember what's on the box so its console panel can load the matching
      // Task Profile (utility controls / telemetry).
      const name = discovery.sketches.find((s) => s.path === selected)?.name ?? selected;
      store.setFlashed(box, { path: selected, name });
      setResult({
        ok: true,
        message: res.resumedPassthrough
          ? "Flashed. Passthrough resumed — the sketch's output is in the console."
          : "Flashed.",
      });
    } catch (err) {
      setResult({ ok: false, message: err instanceof Error ? err.message : String(err) });
    }
    setStage("done");
  }

  const { state } = discovery.library;

  return (
    <Modal open={open} onClose={onClose} title={`Flash box ${box}`}>
      {stage === "pick" && (
        <>
          {state === "ok" && (
            <>
              <div className="flex flex-col gap-4">
                {byCategory.map(([category, sketches]) => (
                  <div key={category}>
                    <h3 className="mb-1.5 font-display text-[11px] font-medium tracking-wide text-static uppercase">
                      {category}
                    </h3>
                    <div className="flex flex-col gap-0.5">
                      {sketches.map((sketch) => (
                        <label
                          key={sketch.path}
                          className={`flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-1.5 transition-colors ${
                            selected === sketch.path
                              ? "bg-pulsar/18 text-starlight"
                              : "text-static hover:text-starlight"
                          }`}
                        >
                          <input
                            type="radio"
                            name={`sketch-box-${box}`}
                            checked={selected === sketch.path}
                            onChange={() => setSelected(sketch.path)}
                            className="accent-[var(--color-pulsar)]"
                          />
                          <span className="font-mono text-[12px]">{sketch.name}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              {discovery.skippedCount > 0 && (
                <p
                  className="mt-3 text-[11px]"
                  style={{ color: "var(--color-status-warning)" }}
                >
                  {discovery.skippedCount}{" "}
                  {discovery.skippedCount === 1 ? "item" : "items"} couldn't be read — a
                  sketch folder needs a .ino named after the folder.
                </p>
              )}

              <div className="mt-5 flex items-center justify-between">
                <Button variant="ghost" onClick={() => void refreshSketches()} title="Rescan">
                  <RefreshCw size={13} strokeWidth={1.75} />
                  Refresh
                </Button>
                <Button variant="primary" onClick={() => void flash()} disabled={!selected}>
                  <Zap size={13} strokeWidth={1.75} />
                  Flash
                </Button>
              </div>
            </>
          )}

          {state !== "ok" && (
            <LibraryProblem
              message={discovery.library.message}
              onRefresh={() => void refreshSketches()}
            />
          )}
        </>
      )}

      {stage !== "pick" && (
        <>
          <p className="mb-2 font-mono text-[12px] text-static">
            {stage === "flashing"
              ? log.some((l) => l.phase === "upload")
                ? "uploading…"
                : "compiling…"
              : null}
          </p>

          <ProgressLog log={log} />

          {stage === "done" && result && (
            <div
              className="mt-3 flex items-start gap-2 text-[13px]"
              style={{
                color: result.ok ? "var(--color-status-ok)" : "var(--color-status-error)",
              }}
            >
              {result.ok ? (
                <Check size={15} strokeWidth={2} className="mt-px shrink-0" />
              ) : (
                <CircleAlert size={15} strokeWidth={1.75} className="mt-px shrink-0" />
              )}
              <span>
                {result.message}
                {!result.ok && (
                  <span className="mt-1 block text-[11px] text-static">
                    The box is in ERROR — acknowledge it in the panel to recover.
                  </span>
                )}
              </span>
            </div>
          )}

          {stage === "done" && (
            <div className="mt-4 flex justify-end">
              <Button onClick={onClose}>Close</Button>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function LibraryProblem({
  message,
  onRefresh,
}: {
  message: string | null;
  onRefresh: () => void;
}) {
  // Sketches ship with the app, so a non-ok library is a broken install rather
  // than a wrong setting — there is no picker to send anyone to, and the
  // sidecar's message already says "reinstall". Refresh is offered because a
  // rescan is free and a half-finished install may have completed since.
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-[13px] leading-relaxed text-static">
        {message ??
          "Ephymeris couldn't find the sketches it ships with. The install looks incomplete — reinstalling should fix it."}
      </p>
      <Button onClick={onRefresh}>
        <RefreshCw size={13} strokeWidth={1.75} />
        Refresh
      </Button>
    </div>
  );
}

function ProgressLog({ log }: { log: ProgressEntry[] }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log]);

  return (
    <div
      ref={ref}
      data-selectable
      className="h-52 overflow-y-auto rounded-sm border border-halo bg-void/70 px-2.5 py-1.5 font-mono text-[11px] leading-[1.65]"
    >
      {log.length === 0 ? (
        <span className="text-static/50">waiting for arduino-cli…</span>
      ) : (
        log.map((entry) => (
          <div key={entry.id} className="break-all whitespace-pre-wrap text-static">
            <span className="text-static/50">[{entry.phase}] </span>
            <span className={entry.text.toLowerCase().includes("error") ? "text-[var(--color-status-error)]" : ""}>
              {entry.text}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
