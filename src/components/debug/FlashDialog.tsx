import { Check, CircleAlert, RefreshCw, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import { enqueueFlash } from "@/lib/hardware/commands";
import { useBoxFlash } from "@/lib/hardware/context";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

/**
 * The flashing flow (`ARCHITECTURE.md#flashing`): pick a sketch from the
 * categorized list discovered in the sketch library, then watch
 * compile/upload progress stream in — not a spinner-until-done.
 *
 * The sidecar's flash queue runs it (`ARCHITECTURE.md#the-flash-queue`), behind
 * any other flash on the rig, and ends it in a console at this panel's baud:
 * someone who has just put a sketch on a board wants to talk to it. Closing
 * the dialog stops nothing.
 *
 * The list is the only path to a flashable sketch (`TASKS.md#discovery`),
 * and every library state (`TASKS.md#library-states`) renders distinctly here.
 * The sidecar enforces list membership too; this UI is the convenient face of
 * that rule, not the rule itself.
 */

interface ProgressEntry {
  id: number;
  phase: "compile" | "upload";
  stream: string;
  text: string;
}

type Stage = "pick" | "flashing" | "done";

const IN_HAND = new Set(["queued", "waiting", "flashing"]);

export function FlashDialog({
  box,
  baud,
  open,
  onClose,
}: {
  box: number;
  /** The panel's console baud — what the post-flash console opens at. */
  baud: number;
  open: boolean;
  onClose: () => void;
}) {
  const { client } = useSidecar();
  const { discovery, refreshSketches } = useSettings();
  const row = useBoxFlash(box);
  // Only a Debug flash is this dialog's: a restore or a session flash of the
  // same box is not something it asked for.
  const job = row?.job?.origin === "debug" ? row.job : null;

  const [selected, setSelected] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [log, setLog] = useState<ProgressEntry[]>([]);
  const seq = useRef(0);

  // Fresh start each time the dialog opens — unless a flash of this box is
  // still under way, which it shows rather than offering another.
  useEffect(() => {
    if (open) {
      setSubmitted(false);
      setRefused(null);
      setLog([]);
    }
  }, [open]);

  const inHand = job !== null && IN_HAND.has(job.state);
  const stage: Stage = refused !== null ? "done" : inHand ? "flashing" : submitted ? "done" : "pick";
  const result =
    refused !== null
      ? { ok: false, message: refused }
      : job?.state === "failed"
        ? { ok: false, message: job.detail ?? "The flash failed." }
        : job?.state === "done"
          ? {
              ok: true,
              message:
                job.detail === "console open"
                  ? "Flashed. The console is open — the sketch's output is in it."
                  : "Flashed. Open the console to talk to the sketch.",
            }
          : null;

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
    setLog([]);
    setRefused(null);
    try {
      // The open that ends it toggles DTR, which reboots the Mega: a behaviour
      // sketch prints `READY` into the console and waits there for `START`.
      await enqueueFlash(client, [box], selected, baud);
      setSubmitted(true);
    } catch (err) {
      setRefused(errorMessage(err));
    }
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
              ? job?.state === "flashing"
                ? log.some((l) => l.phase === "upload")
                  ? "uploading…"
                  : "compiling…"
                : (job?.detail ?? "waiting for its turn…")
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
                {!result.ok && refused === null && (
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
