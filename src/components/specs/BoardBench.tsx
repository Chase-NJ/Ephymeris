import { CircleAlert, Loader2, RadioTower, Upload, Zap } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { useAllPortStatuses, useBoardPresence } from "@/lib/hardware/context";
import { errorMessage } from "@/lib/cohorts/commands";
import { boardCapabilities, setBenchHold, uploadTable } from "@/lib/specs/commands";
import { toYaml } from "@/lib/specs/document";
import type { SpecDocument } from "@/lib/specs/types";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { CMD, EVT } from "@/lib/ws/protocol";
import type { BoardCapabilities, UploadProgressData } from "@/lib/ws/protocol";

/**
 * Bench boxes — probe a board's CAP banner and put a compiled table on it.
 *
 * TWO EXPLICIT CLICKS, NEVER ONE COMBINED BUTTON. Flashing destroys whatever
 * is on the box, and the app's own baseline rules already treat an unrequested
 * flash as unacceptable — so "flash the interpreter" and "upload the table"
 * are separate, and each says what it is about to do.
 *
 * While this panel is mounted the utility baseline is bench-held: without
 * that, an upload ends with the port falling IDLE and the baseline quietly
 * reflashing BOX_Utility over the interpreter — the uploaded table dies with
 * it, and nothing errors. Held on mount, released on unmount, deliberately a
 * separate flag from the session hold.
 *
 * And the line that governs everything here, kept in view rather than in a
 * dismissible toast: THIS PATH IS NOT FOR ANIMALS. The interpreter is proved
 * off-target and has never driven a pin; a box carrying TaskRunner accepts a
 * table and reports whether it fits. It runs no trial and delivers no reward.
 * Structurally enforced too — no wire command ties a spec to a session.
 */
export function BoardBench({
  specId,
  doc,
  compiled,
}: {
  specId: string;
  doc: SpecDocument;
  /** Whether the live compile currently yields a table — the upload gate. */
  compiled: boolean;
}) {
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const { settings, discovery } = useSettings();
  const ports = useAllPortStatuses();
  const presence = useBoardPresence();

  const [caps, setCaps] = useState<Record<number, BoardCapabilities>>({});
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Record<number, string>>({});

  // The bench hold brackets this panel's lifetime. Fire-and-forget on both
  // edges: a failed hold call surfaces on the next restore's own reporting.
  useEffect(() => {
    if (!connected) return;
    void setBenchHold(client, true).catch(() => {});
    return () => {
      void setBenchHold(client, false).catch(() => {});
    };
  }, [client, connected]);

  // Upload progress, folded into the per-box busy line.
  useEffect(
    () =>
      client.on(EVT.UPLOAD_PROGRESS, (data) => {
        const p = data as UploadProgressData;
        const text =
          p.phase === "transfer" && p.chunk !== null
            ? `transfer · chunk ${p.chunk}`
            : (p.text ?? p.phase);
        setBusy((prev) =>
          prev[p.box] === undefined ? prev : { ...prev, [p.box]: text },
        );
      }),
    [client],
  );

  const bound = settings.boxes.filter((b) => b.hardwareId !== null);
  const interpreterSketch = discovery.sketches.find((s) => s.name === "TaskRunner_Dev");

  /**
   * One box's action, with its busy label and its error landing in the card.
   *
   * Every action here has the same shape and the same failure story — the box
   * says what went wrong and nothing else on the panel changes — so the
   * bookkeeping lives once and the three callers below are just their own work.
   */
  async function run(box: number, label: string, work: () => Promise<void>) {
    setBusy((prev) => ({ ...prev, [box]: label }));
    setNotes((prev) => ({ ...prev, [box]: "" }));
    try {
      await work();
    } catch (err) {
      setNotes((prev) => ({ ...prev, [box]: errorMessage(err) }));
    } finally {
      setBusy((prev) => {
        const { [box]: _done, ...rest } = prev;
        return rest;
      });
    }
  }

  /** Read the banner and show it. Also the tail of a flash, so the card's
   * firmware line reflects what is now on the board rather than what was. */
  async function readCaps(box: number) {
    const reply = await boardCapabilities(client, box);
    setCaps((prev) => ({ ...prev, [box]: reply }));
  }

  const probe = (box: number) => run(box, "probing…", () => readCaps(box));

  const flashInterpreter = (box: number) =>
    run(box, "flashing TaskRunner_Dev…", async () => {
      if (!interpreterSketch) return;
      await client.call(CMD.PORT_FLASH, { box, sketchPath: interpreterSketch.path });
      await readCaps(box);
    });

  const upload = (box: number) =>
    run(box, "starting…", async () => {
      const reply = await uploadTable(client, box, specId, toYaml(doc));
      // Three lines rather than one sentence: what landed, how it went, and
      // the two verification numbers. As a single concatenation this wrapped
      // into an unreadable paragraph in a narrow card, and the numbers that
      // matter most were at the end of it.
      setNotes((prev) => ({
        ...prev,
        [box]: [
          `✓ ${reply.specId} (${reply.specHash})`,
          `${reply.nBytes} bytes in ${reply.chunks} chunks · ${(reply.seconds * 1000).toFixed(0)} ms`,
          // Both numbers, because they answer different questions: the CRC says
          // the bytes arrived, the digest says they decoded into the right
          // fields. A transfer can be perfect and a decode wrong.
          `crc ${reply.crc32} · digest ${reply.digest}`,
          ...reply.notes,
        ].join("\n"),
      }));
      setCaps((prev) => ({ ...prev, [box]: reply.caps }));
    });

  return (
    <section className="flex flex-col gap-1.5">
      <header className="border-b border-halo pb-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-static">
          Bench boxes
        </span>
      </header>

      {/* Permanent, not dismissible. The category is named Bench for the same
      reason this strip exists. */}
      <div
        className="flex items-start gap-2 rounded-sm border border-halo px-2.5 py-2 text-[11px] leading-relaxed"
        style={{ color: "var(--color-status-warning)" }}
      >
        <CircleAlert size={13} strokeWidth={1.75} className="mt-px shrink-0" />
        <span>
          <span className="font-medium">Bench only.</span> The table interpreter
          is proved off-target and has never driven a pin — a box carrying
          TaskRunner accepts a table and reports whether it fits. It runs no
          trial and delivers no reward. Do not put an animal in a box running
          this.
        </span>
      </div>

      {bound.length === 0 ? (
        <p className="text-[11px] text-static/70">
          No boxes are bound to a board yet — bind them on Config.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {bound.map((binding) => {
            const box = binding.box;
            const portState = ports[box]?.state ?? "IDLE";
            const detected = presence.some((b) => b.hardwareId === binding.hardwareId);
            const boxCaps = caps[box];
            const busyText = busy[box];
            const idle = portState === "IDLE" || portState === "PASSTHROUGH";
            return (
              <div key={box} className="rounded-sm border border-halo px-2.5 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-starlight">
                    {binding.label}
                    <span className="ml-2 text-[9px] text-static/70">{portState}</span>
                    {!detected && (
                      <span className="ml-2 text-[9px] text-static/50">no board detected</span>
                    )}
                  </span>
                  <span className="flex items-center gap-1.5">
                    {busyText ? (
                      <span className="flex items-center gap-1.5 font-mono text-[10px] text-static">
                        <Loader2 size={11} strokeWidth={1.75} className="animate-spin" />
                        {busyText}
                      </span>
                    ) : (
                      <>
                        <Button
                          variant="ghost"
                          disabled={!connected || !detected || !idle}
                          onClick={() => void probe(box)}
                          title="Read the board's CAP banner — changes nothing on it (one reset)"
                        >
                          <RadioTower size={12} strokeWidth={1.75} />
                          Probe
                        </Button>
                        {boxCaps && !boxCaps.present && (
                          <Button
                            disabled={!connected || !detected || !idle || !interpreterSketch}
                            onClick={() => void flashInterpreter(box)}
                            title={
                              interpreterSketch
                                ? "Replace this box's firmware with the table interpreter (destructive)"
                                : "TaskRunner_Dev is not in the bundled library"
                            }
                          >
                            <Zap size={12} strokeWidth={1.75} />
                            Flash TaskRunner_Dev
                          </Button>
                        )}
                        {boxCaps?.present && (
                          <Button
                            variant="primary"
                            disabled={!connected || !detected || !idle || !compiled}
                            onClick={() => void upload(box)}
                            title={
                              compiled
                                ? "Put the compiled table on this box"
                                : "The spec doesn't compile — no table exists to upload"
                            }
                          >
                            <Upload size={12} strokeWidth={1.75} />
                            Upload table
                          </Button>
                        )}
                      </>
                    )}
                  </span>
                </div>

                {boxCaps && (
                  <p className="mt-1 font-mono text-[9.5px] text-static/70">
                    {boxCaps.present
                      ? `interpreter @ ${boxCaps.baud} · ` +
                        Object.entries(boxCaps.values)
                          .map(([k, v]) => `${k}=${v}`)
                          .join(" ")
                      : `not an interpreter box (no CAP) · answered @ ${boxCaps.baud}`}
                  </p>
                )}
                {notes[box] && (
                  <p
                    className="mt-1 text-[10px] leading-relaxed whitespace-pre-line"
                    style={{
                      color: notes[box]!.startsWith("✓")
                        ? "var(--color-status-ok)"
                        : "var(--color-status-error)",
                    }}
                  >
                    {notes[box]}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
